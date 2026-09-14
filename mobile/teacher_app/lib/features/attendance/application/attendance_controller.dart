import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../shared/models/attendance.dart';
import '../../students/data/students_repository.dart';
import '../data/attendance_repository.dart';

/// Composite key: (section_id, YYYY-MM-DD) for the family.
@immutable
class AttendanceKey {
  final int sectionId;
  final DateTime date;
  const AttendanceKey(this.sectionId, this.date);
  @override
  int get hashCode => Object.hash(sectionId, date.year, date.month, date.day);
  @override
  bool operator ==(Object other) =>
      other is AttendanceKey &&
      other.sectionId == sectionId &&
      other.date.year == date.year &&
      other.date.month == date.month &&
      other.date.day == date.day;
}

@immutable
class AttendanceFormState {
  final Map<int, AttendanceMark> marks;
  final int totalStudents;
  final bool saving;

  const AttendanceFormState({
    required this.marks,
    required this.totalStudents,
    this.saving = false,
  });

  int count(AttendanceStatus s) =>
      marks.values.where((m) => m.status == s).length;
  int get unmarked =>
      totalStudents - marks.values.where((m) => m.status != null).length;

  AttendanceFormState copyWith({
    Map<int, AttendanceMark>? marks,
    int? totalStudents,
    bool? saving,
  }) => AttendanceFormState(
        marks: marks ?? this.marks,
        totalStudents: totalStudents ?? this.totalStudents,
        saving: saving ?? this.saving,
      );
}

class AttendanceController
    extends FamilyAsyncNotifier<AttendanceFormState, AttendanceKey> {
  @override
  Future<AttendanceFormState> build(AttendanceKey key) async {
    final repo = ref.read(attendanceRepositoryProvider);
    // Pre-fill from server + load student list to know total count
    final existing = await repo.fetchExisting(key.sectionId, key.date);
    final students = await ref
        .read(studentsRepositoryProvider)
        .bySection(key.sectionId);
    // Ensure every student has a slot in the map (even if unmarked)
    final marks = <int, AttendanceMark>{
      for (final s in students)
        s.enrollmentId: existing[s.enrollmentId] ?? const AttendanceMark(),
    };
    return AttendanceFormState(marks: marks, totalStudents: students.length);
  }

  void setStatus(int enrollmentId, AttendanceStatus status) {
    final s = state.valueOrNull;
    if (s == null) return;
    final newMarks = Map<int, AttendanceMark>.from(s.marks);
    final existing = newMarks[enrollmentId] ?? const AttendanceMark();
    newMarks[enrollmentId] = existing.copyWith(status: status, dirty: true);
    state = AsyncData(s.copyWith(marks: newMarks));
  }

  void setNotes(int enrollmentId, String? notes) {
    final s = state.valueOrNull;
    if (s == null) return;
    final newMarks = Map<int, AttendanceMark>.from(s.marks);
    final existing = newMarks[enrollmentId] ?? const AttendanceMark();
    newMarks[enrollmentId] = existing.copyWith(notes: notes, dirty: true);
    state = AsyncData(s.copyWith(marks: newMarks));
  }

  void markAllPresent() {
    final s = state.valueOrNull;
    if (s == null) return;
    final newMarks = <int, AttendanceMark>{};
    for (final entry in s.marks.entries) {
      newMarks[entry.key] = entry.value.status == null
          ? entry.value.copyWith(status: AttendanceStatus.present, dirty: true)
          : entry.value;
    }
    state = AsyncData(s.copyWith(marks: newMarks));
  }

  Future<Map<String, int>> submit(int sectionId, DateTime date) async {
    final s = state.valueOrNull;
    if (s == null) throw StateError('form not loaded');
    state = AsyncData(s.copyWith(saving: true));
    try {
      final result = await ref
          .read(attendanceRepositoryProvider)
          .saveBulk(sectionId: sectionId, date: date, marks: s.marks);
      // Clear dirty flags after successful save
      final cleaned = <int, AttendanceMark>{
        for (final e in s.marks.entries)
          e.key: e.value.copyWith(dirty: false),
      };
      state = AsyncData(s.copyWith(marks: cleaned, saving: false));
      return result;
    } catch (e) {
      state = AsyncData(s.copyWith(saving: false));
      rethrow;
    }
  }
}

final attendanceControllerProvider = AsyncNotifierProvider.family<
    AttendanceController, AttendanceFormState, AttendanceKey>(
  AttendanceController.new,
);

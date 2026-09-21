import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class TeacherSection {
  final int id;
  final int sectionId, subjectId;
  final String subject;
  final String? grade, className, room;
  final int studentCount, weeklyPeriods;
  const TeacherSection({
    required this.id, required this.sectionId, required this.subjectId,
    required this.subject,
    this.grade, this.className, this.room,
    this.studentCount = 0, this.weeklyPeriods = 0,
  });
  factory TeacherSection.fromJson(Map<String, dynamic> j) => TeacherSection(
    id: (j['id'] as num).toInt(),
    sectionId: (j['section_id'] as num).toInt(),
    subjectId: (j['subject_id'] as num).toInt(),
    subject: j['subject'] as String? ?? '',
    grade: j['grade'] as String?,
    className: j['class_name'] as String?,
    room: j['room'] as String?,
    studentCount: (j['student_count'] as num?)?.toInt() ?? 0,
    weeklyPeriods: (j['weekly_periods'] as num?)?.toInt() ?? 0,
  );
}

class SectionsTotals {
  final int assignments, students, periods;
  const SectionsTotals({this.assignments = 0, this.students = 0, this.periods = 0});
  factory SectionsTotals.fromJson(Map<String, dynamic> j) => SectionsTotals(
    assignments: (j['assignments'] as num?)?.toInt() ?? 0,
    students:    (j['students']    as num?)?.toInt() ?? 0,
    periods:     (j['periods']     as num?)?.toInt() ?? 0,
  );
}

class SectionsPayload {
  final List<TeacherSection> sections;
  final SectionsTotals totals;
  const SectionsPayload({required this.sections, required this.totals});
  factory SectionsPayload.fromJson(Map<String, dynamic> j) => SectionsPayload(
    sections: ((j['sections'] as List?) ?? [])
      .map((e) => TeacherSection.fromJson((e as Map).cast<String, dynamic>())).toList(),
    totals: SectionsTotals.fromJson(
      ((j['totals'] as Map?) ?? const {}).cast<String, dynamic>()),
  );
}

class SectionsRepository {
  SectionsRepository(this._dio);
  final Dio _dio;
  Future<SectionsPayload> fetch() async {
    final r = await _dio.get(Endpoints.sections);
    return SectionsPayload.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final sectionsRepositoryProvider = Provider<SectionsRepository>((ref) =>
    SectionsRepository(ref.watch(dioProvider)));

final sectionsProvider = FutureProvider.autoDispose<SectionsPayload>((ref) =>
    ref.watch(sectionsRepositoryProvider).fetch());

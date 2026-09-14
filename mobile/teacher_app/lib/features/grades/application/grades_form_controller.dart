import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../students/data/students_repository.dart';
import '../data/grades_repository.dart';

@immutable
class GradesFormKey {
  final int sectionId;
  final int subjectId;
  final int termId;
  final int componentId;
  const GradesFormKey({
    required this.sectionId,
    required this.subjectId,
    required this.termId,
    required this.componentId,
  });
  @override
  int get hashCode => Object.hash(sectionId, subjectId, termId, componentId);
  @override
  bool operator ==(Object other) =>
      other is GradesFormKey &&
      other.sectionId == sectionId &&
      other.subjectId == subjectId &&
      other.termId == termId &&
      other.componentId == componentId;
}

@immutable
class GradesFormState {
  final Map<int, String> inputs; // enrollment_id → raw string in text field
  final Map<int, double> original; // pre-fill snapshot
  final int totalStudents;
  final double maxScore;
  final bool saving;

  const GradesFormState({
    required this.inputs,
    required this.original,
    required this.totalStudents,
    required this.maxScore,
    this.saving = false,
  });

  int get entered =>
      inputs.values.where((v) => v.trim().isNotEmpty).length;

  bool isDirty(int enrollmentId) {
    final raw = inputs[enrollmentId]?.trim() ?? '';
    if (raw.isEmpty) return false;
    final parsed = double.tryParse(raw);
    if (parsed == null) return true;
    final was = original[enrollmentId];
    return was == null || (was - parsed).abs() > 0.001;
  }

  bool isInvalid(int enrollmentId) {
    final raw = inputs[enrollmentId]?.trim() ?? '';
    if (raw.isEmpty) return false;
    final parsed = double.tryParse(raw);
    if (parsed == null) return true;
    return parsed < 0 || parsed > maxScore;
  }

  GradesFormState copyWith({
    Map<int, String>? inputs,
    bool? saving,
  }) => GradesFormState(
        inputs: inputs ?? this.inputs,
        original: original,
        totalStudents: totalStudents,
        maxScore: maxScore,
        saving: saving ?? this.saving,
      );
}

class GradesFormController
    extends FamilyAsyncNotifier<GradesFormState, GradesFormKey> {
  double _maxScore = 100;

  @override
  Future<GradesFormState> build(GradesFormKey key) async {
    // Note: max_score comes from the URL args in the screen and is passed via setMaxScore().
    final repo = ref.read(gradesRepositoryProvider);
    final students = await ref
        .read(studentsRepositoryProvider)
        .bySection(key.sectionId);
    final existing = await repo.fetchExistingScores(
      sectionId: key.sectionId,
      subjectId: key.subjectId,
      termId: key.termId,
      componentId: key.componentId,
    );
    final inputs = <int, String>{
      for (final s in students)
        s.enrollmentId: existing[s.enrollmentId] != null
            ? _fmtScore(existing[s.enrollmentId]!)
            : '',
    };
    return GradesFormState(
      inputs: inputs,
      original: Map<int, double>.from(existing),
      totalStudents: students.length,
      maxScore: _maxScore,
    );
  }

  void setMaxScore(double max) {
    _maxScore = max;
    final s = state.valueOrNull;
    if (s != null) {
      state = AsyncData(GradesFormState(
        inputs: s.inputs,
        original: s.original,
        totalStudents: s.totalStudents,
        maxScore: max,
        saving: s.saving,
      ));
    }
  }

  void setInput(int enrollmentId, String value) {
    final s = state.valueOrNull;
    if (s == null) return;
    final newInputs = Map<int, String>.from(s.inputs);
    newInputs[enrollmentId] = value;
    state = AsyncData(s.copyWith(inputs: newInputs));
  }

  Future<Map<String, int>> submit(GradesFormKey key) async {
    final s = state.valueOrNull;
    if (s == null) throw StateError('form not loaded');
    // Assemble only the dirty + valid entries
    final scores = <int, double>{};
    for (final e in s.inputs.entries) {
      if (!s.isDirty(e.key)) continue;
      if (s.isInvalid(e.key)) continue;
      final parsed = double.parse(e.value.trim());
      scores[e.key] = parsed;
    }
    if (scores.isEmpty) return {'saved': 0, 'rejected': 0};
    state = AsyncData(s.copyWith(saving: true));
    try {
      final result = await ref.read(gradesRepositoryProvider).saveBulk(
            sectionId: key.sectionId,
            subjectId: key.subjectId,
            termId: key.termId,
            componentId: key.componentId,
            scores: scores,
          );
      // Merge saved values into original
      final newOriginal = Map<int, double>.from(s.original);
      newOriginal.addAll(scores);
      state = AsyncData(GradesFormState(
        inputs: s.inputs,
        original: newOriginal,
        totalStudents: s.totalStudents,
        maxScore: s.maxScore,
        saving: false,
      ));
      return result;
    } catch (e) {
      state = AsyncData(s.copyWith(saving: false));
      rethrow;
    }
  }

  String _fmtScore(double v) {
    if (v == v.toInt().toDouble()) return v.toInt().toString();
    return v.toString();
  }
}

final gradesFormControllerProvider = AsyncNotifierProvider.family<
    GradesFormController, GradesFormState, GradesFormKey>(
  GradesFormController.new,
);

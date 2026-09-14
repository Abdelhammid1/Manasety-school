import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/component.dart';
import '../../../shared/models/term.dart';

final gradesRepositoryProvider = Provider<GradesRepository>((ref) {
  return GradesRepository(ref.watch(dioProvider));
});

class GradesRepository {
  final Dio _dio;
  GradesRepository(this._dio);

  Future<List<Term>> fetchTerms() async {
    try {
      final r = await _dio.get(Endpoints.teacherTerms);
      final raw = (r.data['terms'] as List?) ?? const [];
      return raw.map((e) => Term.fromJson(e as Map<String, dynamic>)).toList();
    } catch (e) {
      throw toApi(e);
    }
  }

  Future<List<AssessmentComponentBrief>> fetchComponents(
      {required int subjectId, required int termId}) async {
    try {
      final r = await _dio.get(
        Endpoints.teacherComponents,
        queryParameters: {'subject_id': subjectId, 'term_id': termId},
      );
      final raw = (r.data['components'] as List?) ?? const [];
      return raw
          .map((e) => AssessmentComponentBrief.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }

  Future<Map<int, double>> fetchExistingScores({
    required int sectionId,
    required int subjectId,
    required int termId,
    required int componentId,
  }) async {
    try {
      final r = await _dio.get(
        Endpoints.teacherGrades,
        queryParameters: {
          'section_id': sectionId,
          'subject_id': subjectId,
          'term_id': termId,
          'component_id': componentId,
        },
      );
      final raw = (r.data['entries'] as List?) ?? const [];
      final out = <int, double>{};
      for (final row in raw) {
        final m = row as Map<String, dynamic>;
        out[m['enrollment_id'] as int] = (m['score'] as num).toDouble();
      }
      return out;
    } catch (e) {
      throw toApi(e);
    }
  }

  /// Returns { saved, rejected }.
  Future<Map<String, int>> saveBulk({
    required int sectionId,
    required int subjectId,
    required int termId,
    required int componentId,
    required Map<int, double> scores,
  }) async {
    try {
      final entries = <Map<String, dynamic>>[
        for (final e in scores.entries)
          {
            'enrollment_id': e.key,
            'component_id': componentId,
            'score': e.value,
          },
      ];
      final r = await _dio.post(Endpoints.teacherGrades, data: {
        'section_id': sectionId,
        'subject_id': subjectId,
        'term_id': termId,
        'entries': entries,
      });
      return {
        'saved': (r.data['saved'] as int?) ?? 0,
        'rejected': (r.data['rejected'] as int?) ?? 0,
      };
    } catch (e) {
      throw toApi(e);
    }
  }
}

final termsProvider =
    FutureProvider.autoDispose<List<Term>>((ref) {
  return ref.watch(gradesRepositoryProvider).fetchTerms();
});

/// Component list keyed by (subjectId, termId).
final componentsProvider = FutureProvider.autoDispose
    .family<List<AssessmentComponentBrief>, ({int subjectId, int termId})>(
        (ref, args) {
  return ref
      .watch(gradesRepositoryProvider)
      .fetchComponents(subjectId: args.subjectId, termId: args.termId);
});

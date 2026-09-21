import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class TermInfo {
  final int id, yearId;
  final String? name, startDate, endDate;
  const TermInfo({required this.id, required this.yearId,
    this.name, this.startDate, this.endDate});
  factory TermInfo.fromJson(Map<String, dynamic> j) => TermInfo(
    id: (j['id'] as num).toInt(),
    yearId: (j['year_id'] as num).toInt(),
    name: j['name'] as String?,
    startDate: j['start_date'] as String?,
    endDate: j['end_date'] as String?,
  );
}

class ComponentInfo {
  final int id;
  final String name;
  final double maxScore;
  const ComponentInfo({required this.id, required this.name, required this.maxScore});
  factory ComponentInfo.fromJson(Map<String, dynamic> j) => ComponentInfo(
    id: (j['id'] as num).toInt(),
    name: j['name'] as String? ?? '',
    maxScore: (j['max_score'] as num?)?.toDouble() ?? 0,
  );
}

class GradeEntry {
  final int enrollmentId;
  final double score;
  const GradeEntry({required this.enrollmentId, required this.score});
  factory GradeEntry.fromJson(Map<String, dynamic> j) => GradeEntry(
    enrollmentId: (j['enrollment_id'] as num).toInt(),
    score: (j['score'] as num?)?.toDouble() ?? 0,
  );
}

class GradebookRepository {
  GradebookRepository(this._dio);
  final Dio _dio;

  Future<List<TermInfo>> terms() async {
    final r = await _dio.get(Endpoints.terms);
    return ((r.data as Map)['terms'] as List)
      .map((e) => TermInfo.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<List<ComponentInfo>> components({required int subjectId, required int termId}) async {
    final r = await _dio.get(Endpoints.components,
      queryParameters: {'subject_id': subjectId, 'term_id': termId});
    return ((r.data as Map)['components'] as List)
      .map((e) => ComponentInfo.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<List<GradeEntry>> existing({required int sectionId, required int subjectId,
      required int termId, required int componentId}) async {
    final r = await _dio.get(Endpoints.gradesExisting, queryParameters: {
      'section_id': sectionId, 'subject_id': subjectId,
      'term_id': termId, 'component_id': componentId,
    });
    return ((r.data as Map)['entries'] as List)
      .map((e) => GradeEntry.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<Map<String, dynamic>> save({required int sectionId, required int subjectId,
      required int termId, required List<Map<String, dynamic>> entries}) async {
    final r = await _dio.post(Endpoints.gradesRecord, data: {
      'section_id': sectionId, 'subject_id': subjectId,
      'term_id': termId, 'entries': entries,
    });
    return (r.data as Map).cast<String, dynamic>();
  }
}

final gradebookRepositoryProvider = Provider<GradebookRepository>((ref) =>
    GradebookRepository(ref.watch(dioProvider)));

final termsProvider = FutureProvider.autoDispose<List<TermInfo>>((ref) =>
    ref.watch(gradebookRepositoryProvider).terms());

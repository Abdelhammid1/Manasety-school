import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/student_brief.dart';

final studentsRepositoryProvider = Provider<StudentsRepository>((ref) {
  return StudentsRepository(ref.watch(dioProvider));
});

class StudentsRepository {
  final Dio _dio;
  StudentsRepository(this._dio);

  Future<List<StudentBrief>> bySection(int sectionId) async {
    try {
      final r = await _dio.get(
        Endpoints.teacherStudents,
        queryParameters: {'section_id': sectionId},
      );
      final raw = (r.data['students'] as List?) ?? const [];
      return raw
          .map((e) => StudentBrief.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final sectionStudentsProvider =
    FutureProvider.autoDispose.family<List<StudentBrief>, int>((ref, id) {
  return ref.watch(studentsRepositoryProvider).bySection(id);
});

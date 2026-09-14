import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/year_result.dart';

final resultsRepositoryProvider = Provider<ResultsRepository>((ref) {
  return ResultsRepository(ref.watch(dioProvider));
});

class ResultsRepository {
  final Dio _dio;
  ResultsRepository(this._dio);

  Future<List<YearResult>> forChild(int studentId) async {
    try {
      final r = await _dio.get(Endpoints.parentChildResults(studentId));
      final raw = (r.data['results'] as List?) ?? const [];
      return raw
          .map((e) => YearResult.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childResultsProvider =
    FutureProvider.autoDispose.family<List<YearResult>, int>((ref, id) {
  return ref.watch(resultsRepositoryProvider).forChild(id);
});

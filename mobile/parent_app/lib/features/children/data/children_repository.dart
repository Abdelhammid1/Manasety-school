import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/child_brief.dart';

final childrenRepositoryProvider = Provider<ChildrenRepository>((ref) {
  return ChildrenRepository(ref.watch(dioProvider));
});

class ChildrenRepository {
  final Dio _dio;
  ChildrenRepository(this._dio);

  Future<List<ChildBrief>> list() async {
    try {
      final r = await _dio.get(Endpoints.parentChildren);
      final raw = (r.data['children'] as List?) ?? const [];
      return raw
          .map((e) => ChildBrief.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childrenProvider = FutureProvider.autoDispose<List<ChildBrief>>((ref) {
  return ref.watch(childrenRepositoryProvider).list();
});

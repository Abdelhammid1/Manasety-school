import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import 'package:manasety_ui/manasety_ui.dart';
final materialsRepositoryProvider = Provider<MaterialsRepository>((ref) {
  return MaterialsRepository(ref.watch(dioProvider));
});

class MaterialsRepository {
  final Dio _dio;
  MaterialsRepository(this._dio);

  Future<List<MaterialItem>> forChild(int studentId) async {
    try {
      final r = await _dio.get(Endpoints.parentChildMaterials(studentId));
      final raw = (r.data['materials'] as List?) ?? const [];
      return raw
          .map((e) => MaterialItem.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childMaterialsProvider =
    FutureProvider.autoDispose.family<List<MaterialItem>, int>((ref, id) {
  return ref.watch(materialsRepositoryProvider).forChild(id);
});

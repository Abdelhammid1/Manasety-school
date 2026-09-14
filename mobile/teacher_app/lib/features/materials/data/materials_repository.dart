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

  Future<List<MaterialItem>> teacherList() async {
    try {
      final r = await _dio.get(Endpoints.teacherMaterials);
      final raw = (r.data['materials'] as List?) ?? const [];
      return raw
          .map((e) => MaterialItem.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }

  /// Sprint 10 — create a "link" material via JSON.
  Future<MaterialItem> createLink({
    required int sectionId,
    required int subjectId,
    required String title,
    String? description,
    required String url,
  }) async {
    try {
      final r = await _dio.post(Endpoints.teacherMaterials, data: {
        'section_id': sectionId,
        'subject_id': subjectId,
        'title': title,
        'description': description,
        'kind': 'link',
        'external_url': url,
      });
      final data = r.data as Map<String, dynamic>;
      // The POST returns {id, title}; refetch the full item shape.
      return MaterialItem.fromJson({
        'id': data['id'],
        'title': data['title'],
        'kind': 'link',
        'external_url': url,
        'section_name': '',
        'subject_name': '',
        'created_at': DateTime.now().toIso8601String(),
      });
    } catch (e) {
      throw toApi(e);
    }
  }

  /// Sprint 10 — multipart upload of a file material (PDF or image).
  Future<MaterialItem> uploadFile({
    required int sectionId,
    required int subjectId,
    required String title,
    String? description,
    required String filePath,
    void Function(int sent, int total)? onProgress,
  }) async {
    try {
      final form = FormData.fromMap({
        'section_id': sectionId,
        'subject_id': subjectId,
        'title': title,
        if (description != null && description.isNotEmpty)
          'description': description,
        'file': await MultipartFile.fromFile(filePath),
      });
      final r = await _dio.post(
        Endpoints.teacherUpload,
        data: form,
        onSendProgress: onProgress,
      );
      return MaterialItem.fromJson({
        'id': r.data['id'],
        'title': r.data['title'],
        'kind': r.data['kind'] ?? 'file',
        'file_path': r.data['file_path'],
        'section_name': r.data['section_name'] ?? '',
        'subject_name': '',
        'created_at': DateTime.now().toIso8601String(),
      });
    } catch (e) {
      throw toApi(e);
    }
  }
}

final teacherMaterialsProvider =
    FutureProvider.autoDispose<List<MaterialItem>>((ref) {
  return ref.watch(materialsRepositoryProvider).teacherList();
});

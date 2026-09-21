import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class MaterialItem {
  final int id;
  final String title, kind;
  final String? description, externalUrl, filePath, sectionName, subjectName, createdAt;
  const MaterialItem({
    required this.id, required this.title, required this.kind,
    this.description, this.externalUrl, this.filePath,
    this.sectionName, this.subjectName, this.createdAt,
  });
  factory MaterialItem.fromJson(Map<String, dynamic> j) => MaterialItem(
    id: (j['id'] as num).toInt(),
    title: j['title'] as String? ?? '',
    kind: j['kind'] as String? ?? 'link',
    description: j['description'] as String?,
    externalUrl: j['external_url'] as String?,
    filePath: j['file_path'] as String?,
    sectionName: j['section_name'] as String?,
    subjectName: j['subject_name'] as String?,
    createdAt: j['created_at'] as String?,
  );
}

class MaterialsRepository {
  MaterialsRepository(this._dio);
  final Dio _dio;
  Future<List<MaterialItem>> list() async {
    final r = await _dio.get(Endpoints.materials);
    return ((r.data as Map)['materials'] as List)
      .map((e) => MaterialItem.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<MaterialItem> create({
    required int sectionId, required int subjectId,
    required String title, required String kind,
    String? externalUrl, String? description,
  }) async {
    final r = await _dio.post(Endpoints.materials, data: {
      'section_id': sectionId, 'subject_id': subjectId,
      'title': title, 'kind': kind,
      if (externalUrl != null) 'external_url': externalUrl,
      if (description != null) 'description': description,
    });
    return MaterialItem.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final materialsRepositoryProvider = Provider<MaterialsRepository>((ref) =>
    MaterialsRepository(ref.watch(dioProvider)));

final materialsProvider = FutureProvider.autoDispose<List<MaterialItem>>((ref) =>
    ref.watch(materialsRepositoryProvider).list());

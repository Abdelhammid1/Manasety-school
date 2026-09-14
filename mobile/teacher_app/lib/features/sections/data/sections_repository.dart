import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/section_brief.dart';

final sectionsRepositoryProvider = Provider<SectionsRepository>((ref) {
  return SectionsRepository(ref.watch(dioProvider));
});

class SectionsRepository {
  final Dio _dio;
  SectionsRepository(this._dio);

  Future<List<SectionBrief>> list() async {
    try {
      final r = await _dio.get(Endpoints.teacherSections);
      final raw = (r.data['sections'] as List?) ?? const [];
      return raw
          .map((e) => SectionBrief.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final sectionsProvider = FutureProvider.autoDispose<List<SectionBrief>>((ref) {
  return ref.watch(sectionsRepositoryProvider).list();
});

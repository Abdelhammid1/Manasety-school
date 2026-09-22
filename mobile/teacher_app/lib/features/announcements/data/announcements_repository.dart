import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class AnnouncementItem {
  final int id;
  final String title, body;
  final bool isPinned;
  final int? sectionId;
  final String? sectionName, authorName, createdAt;
  const AnnouncementItem({
    required this.id, required this.title, required this.body,
    this.isPinned = false, this.sectionId,
    this.sectionName, this.authorName, this.createdAt,
  });
  factory AnnouncementItem.fromJson(Map<String, dynamic> j) => AnnouncementItem(
    id: (j['id'] as num).toInt(),
    title: j['title'] as String? ?? '',
    body: j['body'] as String? ?? '',
    isPinned: j['is_pinned'] as bool? ?? false,
    sectionId: (j['section_id'] as num?)?.toInt(),
    sectionName: j['section_name'] as String?,
    authorName: j['author_name'] as String?,
    createdAt: j['created_at'] as String?,
  );
}

class AnnouncementsRepository {
  AnnouncementsRepository(this._dio);
  final Dio _dio;
  Future<List<AnnouncementItem>> list() async {
    final r = await _dio.get(Endpoints.announcements);
    return ((r.data as Map)['announcements'] as List)
      .map((e) => AnnouncementItem.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<AnnouncementItem> create({
    required String title, required String body,
    int? sectionId, bool isPinned = false,
  }) async {
    final r = await _dio.post(Endpoints.announcements, data: {
      'title': title, 'body': body,
      if (sectionId != null) 'section_id': sectionId,
      'is_pinned': isPinned,
    });
    return AnnouncementItem.fromJson(
      ((r.data as Map)['announcement'] as Map).cast<String, dynamic>());
  }
  Future<void> delete(int id) async {
    await _dio.delete('${Endpoints.announcements}/$id');
  }
}

final announcementsRepositoryProvider = Provider<AnnouncementsRepository>((ref) =>
    AnnouncementsRepository(ref.watch(dioProvider)));

final announcementsProvider = FutureProvider.autoDispose<List<AnnouncementItem>>((ref) =>
    ref.watch(announcementsRepositoryProvider).list());

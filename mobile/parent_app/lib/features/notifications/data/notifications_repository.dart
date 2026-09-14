import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/notification_item.dart';

final notificationsRepositoryProvider = Provider<NotificationsRepository>((ref) {
  return NotificationsRepository(ref.watch(dioProvider));
});

class NotificationsRepository {
  final Dio _dio;
  NotificationsRepository(this._dio);

  Future<List<NotificationItem>> list() async {
    try {
      final r = await _dio.get(Endpoints.parentNotifications);
      final raw = (r.data['notifications'] as List?) ?? const [];
      return raw
          .map((e) => NotificationItem.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }

  /// Day 7 — mark a single notification as read server-side.
  Future<void> markRead(int id) async {
    try {
      await _dio.post(Endpoints.notificationRead(id));
    } catch (_) {
      // Silently ignore — the UI already updated optimistically.
    }
  }
}

final parentNotificationsProvider =
    FutureProvider.autoDispose<List<NotificationItem>>((ref) {
  return ref.watch(notificationsRepositoryProvider).list();
});

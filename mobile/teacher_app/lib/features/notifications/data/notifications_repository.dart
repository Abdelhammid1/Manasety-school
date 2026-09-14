import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../shared/models/notification_item.dart';

/// Phase 1: لا توجد قناة إشعارات مخصّصة للمعلم بعد — نعرض قائمة فارغة.
/// سيُربط هذا بإشعارات المعلم في Phase 3.
final teacherNotificationsProvider =
    FutureProvider.autoDispose<List<NotificationItem>>((ref) async {
  // المرحلة الأولى: قائمة فارغة. يُحافظ Riverpod على تواقيع متشابهة مع تطبيق ولي الأمر.
  ref.watch(_unusedDioProvider); // ensures Dio is alive for consistency
  return const <NotificationItem>[];
});

final _unusedDioProvider = Provider<Dio>((ref) => ref.watch(dioProvider));

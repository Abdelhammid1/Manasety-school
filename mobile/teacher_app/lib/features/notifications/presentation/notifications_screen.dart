import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/notifications_repository.dart';

/// Teacher notifications — Day 7 grouped feed. The underlying provider is a
/// Phase-1 stub returning an empty list, so today this screen renders the
/// EmptyState. When Phase 3 wires teacher notifications the UI is ready.
class NotificationsScreen extends ConsumerWidget {
  const NotificationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifs = ref.watch(teacherNotificationsProvider);
    // Day 13 — was missing an AppRefreshIndicator; now users can pull-to-refresh
    // both when the list is populated and (via RefreshableEmpty) when empty.
    return AppRefreshIndicator(
      onRefresh: () async {
        ref.invalidate(teacherNotificationsProvider);
        await ref.read(teacherNotificationsProvider.future);
      },
      child: AsyncValueWidget(
        value: notifs,
        onRetry: () => ref.invalidate(teacherNotificationsProvider),
        data: (list) {
          if (list.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.notifications_none_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.bell),
                title: 'لا توجد إشعارات',
                description: 'سيظهر هنا أي تنبيه يخصّك من إدارة المؤسسة.',
              ),
            );
          }
          final cells = [
            for (final n in list)
              NotificationCell(
                id: n.id,
                kind: n.kind,
                message: n.displayMessage,
                createdAt: n.createdAt,
                unread: n.status != 'read',
              ),
          ];
          return NotificationGroupList(items: cells);
        },
      ),
    );
  }
}

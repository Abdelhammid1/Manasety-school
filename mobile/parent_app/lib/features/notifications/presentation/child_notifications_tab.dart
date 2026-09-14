import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/notifications_repository.dart';

/// Day 7 — grouped feed (اليوم / أمس / هذا الأسبوع / …) with unread dots.
/// Tap marks read on the server; the UI updates immediately via optimistic
/// provider invalidation.
class ChildNotificationsTab extends ConsumerWidget {
  const ChildNotificationsTab({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final notifs = ref.watch(parentNotificationsProvider);
    return AppRefreshIndicator(
      onRefresh: () async {
        ref.invalidate(parentNotificationsProvider);
        await ref.read(parentNotificationsProvider.future);
      },
      child: AsyncValueWidget(
        value: notifs,
        onRetry: () => ref.invalidate(parentNotificationsProvider),
        data: (list) {
          if (list.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.notifications_none_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.bell),
                title: 'لا توجد إشعارات بعد',
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
                onTap: () async {
                  await ref
                      .read(notificationsRepositoryProvider)
                      .markRead(n.id);
                  ref.invalidate(parentNotificationsProvider);
                },
              ),
          ];
          return NotificationGroupList(items: cells);
        },
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../attendance/presentation/child_attendance_tab.dart';
import '../../invoices/presentation/child_invoices_tab.dart';
import '../../materials/presentation/child_materials_tab.dart';
import '../../notifications/data/notifications_repository.dart';
import '../../notifications/presentation/child_notifications_tab.dart';
import '../../results/presentation/child_results_tab.dart';
import '../../schedule/presentation/child_schedule_tab.dart';
import '../data/children_repository.dart';

/// Tab index enum kept in sync with the tabs list below.
/// Sprint 10 audit fix — FCM deep-links target /children/:id/<tabName>
/// so the router maps a sub-path to the initialIndex here.
const _tabByName = <String, int>{
  'schedule': 0,
  'attendance': 1,
  'results': 2,
  'invoices': 3,
  'materials': 4,
  'notifications': 5,
};

int tabIndexFromName(String? name) => _tabByName[name] ?? 0;

class ChildDetailScreen extends ConsumerWidget {
  final int childId;
  final int initialTab;
  const ChildDetailScreen({
    super.key,
    required this.childId,
    this.initialTab = 0,
  });

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final children = ref.watch(childrenProvider);
    final name = children.maybeWhen(
      data: (list) {
        final match = list.where((c) => c.id == childId).toList();
        return match.isNotEmpty ? match.first.fullName : 'الطالب';
      },
      orElse: () => 'الطالب',
    );
    // Day 7 — unread count drives the small red dot on the الإشعارات tab.
    final unread = ref
            .watch(parentNotificationsProvider)
            .valueOrNull
            ?.where((n) => n.status != 'read')
            .length ??
        0;

    return DefaultTabController(
      length: 6,
      initialIndex: initialTab.clamp(0, 5),
      child: Scaffold(
        appBar: AppBar(
          // Day 10 — Hero destination matching the child-list card's avatar.
          leading: Padding(
            padding: const EdgeInsetsDirectional.only(start: 12, top: 8, bottom: 8),
            // Day 12 — Hero avatar is decorative; the AppBar title beside it
            // already announces the child's name.
            child: ExcludeSemantics(
              child: Hero(
                tag: 'child-avatar-$childId',
                child: Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.2),
                    shape: BoxShape.circle,
                  ),
                  alignment: Alignment.center,
                  child: const Icon(Icons.person, size: 18, color: Colors.white),
                ),
              ),
            ),
          ),
          leadingWidth: 52,
          title: Text(name),
          bottom: TabBar(
            isScrollable: true,
            indicatorColor: AppColors.gold,
            indicatorWeight: 3,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white.withValues(alpha: 0.7),
            labelStyle: const TextStyle(fontWeight: FontWeight.w700),
            tabs: [
              const Tab(text: 'الجدول'),
              const Tab(text: 'الحضور'),
              const Tab(text: 'النتائج'),
              const Tab(text: 'الفواتير'),
              const Tab(text: 'المواد'),
              Tab(
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('الإشعارات'),
                    if (unread > 0) ...[
                      const SizedBox(width: 6),
                      // Day 12 — colored dot alone conveys "you have unread"
                      // information; give it a text equivalent for SR/CB users.
                      Semantics(
                        label: '${arabize(unread)} إشعار غير مقروء',
                        child: Container(
                          width: 8,
                          height: 8,
                          decoration: const BoxDecoration(
                            color: AppColors.danger,
                            shape: BoxShape.circle,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          actions: [
            IconButton(
              tooltip: 'تبديل الابن',
              icon: const Icon(Icons.swap_horiz),
              onPressed: () => context.go('/'),
            ),
            IconButton(
              tooltip: 'الحساب',
              icon: const Icon(Icons.person_outline),
              onPressed: () => context.push('/profile'),
            ),
          ],
        ),
        body: TabBarView(
          children: [
            ChildScheduleTab(childId: childId),
            ChildAttendanceTab(childId: childId),
            ChildResultsTab(childId: childId),
            ChildInvoicesTab(childId: childId),
            ChildMaterialsTab(childId: childId),
            const ChildNotificationsTab(),
          ],
        ),
      ),
    );
  }
}

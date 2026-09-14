import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../notifications/data/notifications_repository.dart';
import '../../notifications/presentation/notifications_screen.dart';
import '../../profile/presentation/profile_screen.dart';
import '../../schedule/presentation/teacher_schedule_screen.dart';
import '../../sections/presentation/sections_screen.dart';

class MainScaffold extends ConsumerStatefulWidget {
  const MainScaffold({super.key});

  @override
  ConsumerState<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends ConsumerState<MainScaffold> {
  int _idx = 0;

  // TKT-11/12 — unified "talking-to-you" tone across teacher hub (matches
  // parent's `أبناؤك`). Nav label also becomes `فصولك` so the three prior
  // variants (`الفصول` / `فصولي` / `فصولك`) collapse into one.
  static const _titles = ['فصولك', 'جدولك', 'الإشعارات', 'الحساب'];

  @override
  Widget build(BuildContext context) {
    // Day 7 — unread count drives the bell badge.
    final notifs = ref.watch(teacherNotificationsProvider);
    final unread = notifs.valueOrNull
            ?.where((n) => n.status != 'read')
            .length ??
        0;

    return Scaffold(
      appBar: AppBar(title: Text(_titles[_idx])),
      body: IndexedStack(
        index: _idx,
        children: const [
          SectionsScreen(),
          TeacherScheduleScreen(),
          NotificationsScreen(),
          ProfileScreen(),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _idx,
        onDestinationSelected: (i) {
          HapticFeedback.selectionClick();
          setState(() => _idx = i);
        },
        // Both bg + selected-icon colors flow from the theme so the bar adapts
        // to dark mode automatically (no more baked-white bar on dark scaffold).
        backgroundColor: context.tokens.surface,
        indicatorColor: context.tokens.accentBg,
        destinations: [
          NavigationDestination(
            icon: const Icon(Icons.class_outlined),
            selectedIcon: Icon(Icons.class_, color: Theme.of(context).colorScheme.primary),
            label: 'فصولك',
          ),
          NavigationDestination(
            icon: const Icon(Icons.calendar_view_week_outlined),
            selectedIcon:
                Icon(Icons.calendar_view_week, color: Theme.of(context).colorScheme.primary),
            label: 'جدولك',
          ),
          NavigationDestination(
            icon: Badge.count(
              count: unread,
              isLabelVisible: unread > 0,
              child: const Icon(Icons.notifications_outlined),
            ),
            selectedIcon: Badge.count(
              count: unread,
              isLabelVisible: unread > 0,
              child: Icon(Icons.notifications, color: Theme.of(context).colorScheme.primary),
            ),
            label: 'الإشعارات',
          ),
          NavigationDestination(
            icon: const Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person, color: Theme.of(context).colorScheme.primary),
            label: 'الحساب',
          ),
        ],
      ),
    );
  }
}

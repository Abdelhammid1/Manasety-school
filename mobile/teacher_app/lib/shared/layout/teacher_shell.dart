import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../core/router/routes.dart';

/// Bottom-tab shell for the Teacher app.
/// 5 tabs: الرئيسية · فصولي · الحضور · الدرجات · حسابي.
class TeacherShell extends StatelessWidget {
  const TeacherShell({required this.child, super.key});

  final Widget child;

  static const _tabs = <_TabDef>[
    _TabDef(Routes.home,       'الرئيسية', Icons.home_rounded),
    _TabDef(Routes.sections,   'فصولي',    Icons.school_rounded),
    _TabDef(Routes.attendance, 'الحضور',   Icons.fact_check_rounded),
    _TabDef(Routes.gradebook,  'الدرجات',  Icons.grading_rounded),
    _TabDef(Routes.profile,    'حسابي',    Icons.person_rounded),
  ];

  @override
  Widget build(BuildContext context) {
    final location = GoRouterState.of(context).uri.toString();
    final activeIndex = _tabs.indexWhere((t) => location.startsWith(t.path));
    return Scaffold(
      body: SafeArea(child: child),
      bottomNavigationBar: _TabBar(
        tabs: _tabs, activeIndex: activeIndex < 0 ? 0 : activeIndex,
        onTap: (i) => context.go(_tabs[i].path),
      ),
    );
  }
}

class _TabDef {
  final String path; final String label; final IconData icon;
  const _TabDef(this.path, this.label, this.icon);
}

class _TabBar extends StatelessWidget {
  const _TabBar({required this.tabs, required this.activeIndex, required this.onTap});
  final List<_TabDef> tabs;
  final int activeIndex;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: SafeArea(top: false, child: SizedBox(height: 64,
        child: Row(children: [
          for (int i = 0; i < tabs.length; i++)
            Expanded(child: _Item(def: tabs[i], active: i == activeIndex,
              onTap: () => onTap(i))),
        ]),
      )),
    );
  }
}

class _Item extends StatelessWidget {
  const _Item({required this.def, required this.active, required this.onTap});
  final _TabDef def; final bool active; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final color = active ? ManasetyBrand.navy : ManasetyBrand.outline;
    return InkWell(onTap: onTap, child: Column(
      mainAxisAlignment: MainAxisAlignment.center, children: [
        Icon(def.icon, color: color, size: 24),
        const SizedBox(height: 4),
        Text(def.label, style: TextStyle(fontSize: 11,
          fontWeight: active ? FontWeight.w700 : FontWeight.w500, color: color)),
        const SizedBox(height: 4),
        Container(width: 32, height: ManasetyBrand.tabActiveUnderline,
          decoration: BoxDecoration(
            gradient: active ? ManasetyBrand.primaryGradient : null,
            color: active ? null : Colors.transparent,
            borderRadius: BorderRadius.circular(2),
          )),
      ],
    ));
  }
}

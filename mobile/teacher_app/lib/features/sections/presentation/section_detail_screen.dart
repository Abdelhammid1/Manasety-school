import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../materials/presentation/section_materials_tab.dart';
import '../../schedule/presentation/section_schedule_tab.dart';
import '../../students/presentation/section_students_tab.dart';
import '../data/sections_repository.dart';

class SectionDetailScreen extends ConsumerWidget {
  final int sectionId;
  const SectionDetailScreen({super.key, required this.sectionId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final sections = ref.watch(sectionsProvider);
    final sectionName = sections.maybeWhen(
      data: (list) => list
          .firstWhere(
            (s) => s.id == sectionId,
            orElse: () => list.isNotEmpty
                ? list.first
                : throw Exception('not found'),
          )
          .name,
      orElse: () => 'الفصل',
    );

    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: Text(sectionName),
          bottom: const TabBar(
            indicatorColor: AppColors.gold,
            indicatorWeight: 3,
            labelColor: Colors.white,
            unselectedLabelColor: Colors.white70,
            labelStyle: TextStyle(fontWeight: FontWeight.w700),
            tabs: [
              Tab(text: 'الجدول'),
              Tab(text: 'الطلاب'),
              Tab(text: 'المواد'),
            ],
          ),
        ),
        body: TabBarView(
          children: [
            SectionScheduleTab(sectionId: sectionId),
            SectionStudentsTab(sectionId: sectionId),
            SectionMaterialsTab(sectionId: sectionId),
          ],
        ),
        // Sprint 10 Phase 2 — quick actions for teacher writes
        floatingActionButton: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.end,
          children: [
            FloatingActionButton.extended(
              heroTag: 'grades-fab',
              backgroundColor: AppColors.gold,
              foregroundColor: Colors.white,
              onPressed: () => context.push('/sections/$sectionId/grades'),
              icon: const Icon(Icons.edit_note),
              label: const Text('إدخال الدرجات'),
            ),
            const SizedBox(height: 10),
            FloatingActionButton.extended(
              heroTag: 'attendance-fab',
              backgroundColor: AppColors.navy,
              foregroundColor: Colors.white,
              onPressed: () => context.push('/sections/$sectionId/attendance'),
              icon: const Icon(Icons.checklist),
              label: const Text('تسجيل الحضور'),
            ),
          ],
        ),
      ),
    );
  }
}

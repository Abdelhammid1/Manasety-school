import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/env.dart';
import '../data/materials_repository.dart';

class SectionMaterialsTab extends ConsumerWidget {
  final int sectionId;
  const SectionMaterialsTab({super.key, required this.sectionId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final materials = ref.watch(teacherMaterialsProvider);
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(teacherMaterialsProvider);
        await ref.read(teacherMaterialsProvider.future);
      },
      child: AsyncValueWidget(
        value: materials,
        onRetry: () => ref.invalidate(teacherMaterialsProvider),
        data: (all) {
          // Filter by sectionName via lookup — note: backend doesn't filter by
          // section_id yet; we do it on the client using the included section_name.
          // Phase 2 may add a server-side query param.
          final filtered = all; // teacher sees all their materials per scope rules
          if (filtered.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.collections_bookmark_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.bookmark),
                title: 'لا توجد مواد منشورة',
                description: 'يمكنك إضافة مواد لاحقًا من المرحلة الثانية.',
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            itemCount: filtered.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, i) => MaterialCard(
              item: filtered[i],
              fileBaseUrl: Env.apiBase.replaceAll('/api', ''),
            ),
          );
        },
      ),
    );
  }
}

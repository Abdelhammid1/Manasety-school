import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../data/students_repository.dart';

class SectionStudentsTab extends ConsumerWidget {
  final int sectionId;
  const SectionStudentsTab({super.key, required this.sectionId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final students = ref.watch(sectionStudentsProvider(sectionId));
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(sectionStudentsProvider(sectionId));
        await ref.read(sectionStudentsProvider(sectionId).future);
      },
      child: AsyncValueWidget(
        value: students,
        onRetry: () => ref.invalidate(sectionStudentsProvider(sectionId)),
        data: (list) {
          if (list.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.group_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.family),
                title: 'لا يوجد طلاب في هذا الفصل',
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
            itemCount: list.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, i) {
              final s = list[i];
              return Card(
                child: ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                  leading: CircleAvatar(
                    backgroundColor: AppColors.sky.withValues(alpha: 0.5),
                    foregroundColor: Theme.of(context).colorScheme.primary,
                    child: Text(
                      '${i + 1}',
                      style: const TextStyle(fontWeight: FontWeight.w700),
                    ),
                  ),
                  title: Text(
                    s.fullName,
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      color: context.tokens.ink,
                    ),
                  ),
                  subtitle: Text(
                    'الرقم الدائم: ${s.permanentCode}',
                    style: TextStyle(color: context.tokens.muted, fontSize: 12),
                  ),
                ),
              );
            },
          );
        },
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';

import 'package:manasety_ui/manasety_ui.dart';
import '../../../shared/models/year_result.dart';
import '../data/results_repository.dart';

class ChildResultsTab extends ConsumerWidget {
  final int childId;
  const ChildResultsTab({super.key, required this.childId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final results = ref.watch(childResultsProvider(childId));
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(childResultsProvider(childId));
        await ref.read(childResultsProvider(childId).future);
      },
      child: AsyncValueWidget(
        value: results,
        onRetry: () => ref.invalidate(childResultsProvider(childId)),
        data: (list) {
          if (list.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.assignment_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.book),
                title: 'لم تُعتمد نتائج بعد',
                description:
                    'ستظهر هنا النتيجة فور اعتماد إدارة المؤسسة لها.',
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: list.length,
            separatorBuilder: (_, __) => const SizedBox(height: 10),
            itemBuilder: (_, i) => _ResultCard(result: list[i]),
          );
        },
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  final YearResult result;
  const _ResultCard({required this.result});

  StatusKind get _statusKind {
    switch (result.status) {
      case 'pass':
        return StatusKind.success;
      case 'fail':
        return StatusKind.danger;
      case 'conditional':
        return StatusKind.warn;
      default:
        return StatusKind.neutral;
    }
  }

  @override
  Widget build(BuildContext context) {
    final df = DateFormat.yMMMMd('ar');
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '${result.year} — ${result.grade}',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.primary,
                      fontWeight: FontWeight.w800,
                      fontSize: 15,
                    ),
                  ),
                ),
                StatusChip(label: result.statusAr, kind: _statusKind),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              'الفصل: ${result.section} • اعتُمد في ${df.format(result.approvedAt)}',
              style: TextStyle(color: context.tokens.muted, fontSize: 12),
            ),
            const Divider(height: 22),
            Row(
              children: [
                Text(
                  'المعدّل العام',
                  style: TextStyle(color: context.tokens.muted, fontSize: 13),
                ),
                const Spacer(),
                Text(
                  arabize(result.average.toStringAsFixed(2)),
                  // Day 12 hot-fix — gold on white card was ≈1.9:1; goldInk
                  // is the same brand read at ≈5:1.
                  style: const TextStyle(
                    color: AppColors.goldInk,
                    fontWeight: FontWeight.w900,
                    fontSize: 18,
                  ),
                ),
              ],
            ),
            if (result.subjectScores.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text(
                'تفصيل المواد',
                style: TextStyle(
                  color: context.tokens.ink,
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 4),
              ...result.subjectScores.entries.map(
                (e) => SubjectProgressBar(
                  subject: e.key,
                  score: (e.value as num).toDouble(),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

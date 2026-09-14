import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/models/invoice_summary.dart';
import '../data/invoices_repository.dart';

class ChildInvoicesTab extends ConsumerWidget {
  final int childId;
  const ChildInvoicesTab({super.key, required this.childId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final invoices = ref.watch(childInvoicesProvider(childId));
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(childInvoicesProvider(childId));
        await ref.read(childInvoicesProvider(childId).future);
      },
      child: AsyncValueWidget(
        value: invoices,
        onRetry: () => ref.invalidate(childInvoicesProvider(childId)),
        data: (list) {
          if (list.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.receipt_long_outlined,
                illustration: EmptyIllustration(kind: ManasetyEmpty.receipt),
                title: 'لا توجد فواتير',
              ),
            );
          }
          // Sort by status priority then date.
          const order = {'overdue': 0, 'partial': 1, 'pending': 2, 'paid': 3};
          final sorted = [...list]..sort((a, b) {
              final pa = order[a.status] ?? 99;
              final pb = order[b.status] ?? 99;
              if (pa != pb) return pa.compareTo(pb);
              return b.issueDate.compareTo(a.issueDate);
            });
          return ListView.separated(
            padding: const EdgeInsets.all(16),
            itemCount: sorted.length,
            separatorBuilder: (_, __) => const SizedBox(height: 12),
            itemBuilder: (_, i) => _InvoiceRibbon(invoice: sorted[i]),
          );
        },
      ),
    );
  }
}

/// Day 6 — invoice card as a ribbon:
///   • colored top band signaling status at a glance
///   • giant threshold-colored المتبقّي as the hero
///   • horizontal paid-progress bar
///   • compact الإجمالي / المدفوع row + issue/due dates as muted footer
class _InvoiceRibbon extends StatelessWidget {
  final InvoiceSummary invoice;
  const _InvoiceRibbon({required this.invoice});

  Color _statusColor(BuildContext context) {
    switch (invoice.status) {
      case 'paid':
        return AppColors.success;
      case 'partial':
        return AppColors.gold;
      case 'overdue':
        return AppColors.danger;
      case 'pending':
        return AppColors.navy;
      default:
        return context.tokens.muted;
    }
  }

  StatusKind get _statusKind {
    switch (invoice.status) {
      case 'paid':
        return StatusKind.success;
      case 'overdue':
        return StatusKind.danger;
      case 'partial':
        return StatusKind.warn;
      case 'pending':
        return StatusKind.info;
      default:
        return StatusKind.neutral;
    }
  }

  double get _paidPct {
    final total = invoice.totalAmount;
    if (total <= 0) return 0;
    return (invoice.paidAmount / total).clamp(0.0, 1.0);
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final statusColor = _statusColor(context);
    final df = DateFormat.yMMMMd('ar');
    final money = NumberFormat.currency(
      locale: 'ar',
      symbol: 'ج.س',
      decimalDigits: 0,
    );

    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Container(
        decoration: BoxDecoration(
          color: t.surface,
          borderRadius: BorderRadius.circular(14),
          border: Border.all(color: t.border),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Colored status band on top.
            Container(height: 6, color: statusColor),
            Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  // Number + status chip row.
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          arabize(invoice.number),
                          style: TextStyle(
                            color: t.ink,
                            fontWeight: FontWeight.w800,
                            fontSize: 14,
                            fontFeatures: const [FontFeature.tabularFigures()],
                          ),
                        ),
                      ),
                      StatusChip(label: invoice.statusAr, kind: _statusKind),
                    ],
                  ),
                  const SizedBox(height: 14),
                  // Hero: giant remaining amount.
                  Text(
                    'المتبقّي',
                    style: TextStyle(color: t.muted, fontSize: 11),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    arabize(money.format(invoice.remaining)),
                    style: TextStyle(
                      color: statusColor,
                      fontSize: 26,
                      fontWeight: FontWeight.w900,
                      fontFeatures: const [FontFeature.tabularFigures()],
                    ),
                  ),
                  const SizedBox(height: 10),
                  // Paid-percentage progress bar.
                  ClipRRect(
                    borderRadius: BorderRadius.circular(6),
                    child: Container(
                      height: 8,
                      color: t.subtleBg,
                      child: Align(
                        alignment: AlignmentDirectional.centerStart,
                        child: FractionallySizedBox(
                          widthFactor: _paidPct,
                          child: Container(color: statusColor),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 12),
                  // Totals row.
                  Row(
                    children: [
                      _kv(context, 'الإجمالي', arabize(money.format(invoice.totalAmount)), t.ink),
                      const SizedBox(width: 18),
                      _kv(context, 'المدفوع', arabize(money.format(invoice.paidAmount)), AppColors.success),
                    ],
                  ),
                  const SizedBox(height: 6),
                  // Dates footer.
                  Text(
                    arabize('إصدار: ${df.format(invoice.issueDate)}   •   استحقاق: ${df.format(invoice.dueDate)}'),
                    style: TextStyle(color: t.muted, fontSize: 11),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _kv(BuildContext context, String k, String v, Color valueColor) {
    final t = context.tokens;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '$k ',
          style: TextStyle(color: t.muted, fontSize: 12),
        ),
        Text(
          v,
          style: TextStyle(
            color: valueColor,
            fontSize: 13,
            fontWeight: FontWeight.w800,
            fontFeatures: const [FontFeature.tabularFigures()],
          ),
        ),
      ],
    );
  }
}

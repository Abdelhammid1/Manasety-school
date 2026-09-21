import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/api/misc_repositories.dart';

/// Weekly schedule grid — rows = periods, columns = days (RTL).
class TimetableScreen extends ConsumerWidget {
  const TimetableScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(scheduleProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('جدولي الأسبوعي')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(scheduleProvider.future),
        child: async.when(
          data: (rows) {
            if (rows.isEmpty) return _empty();
            final days = _days(rows);
            final periods = _periods(rows);
            return SingleChildScrollView(
              padding: const EdgeInsets.all(16),
              child: _Grid(days: days, periods: periods, rows: rows),
            );
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        ),
      ),
    );
  }

  Widget _empty() => Center(child: Padding(padding: const EdgeInsets.all(24),
    child: Column(mainAxisSize: MainAxisSize.min, children: const [
      Icon(Icons.calendar_month_outlined, size: 72, color: ManasetyBrand.outline),
      SizedBox(height: 12),
      Text('لا جدول بعد', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      SizedBox(height: 6),
      Text('سيظهر الجدول فور اعتماد إسناد الحصص لفصلك.',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant), textAlign: TextAlign.center),
    ])));

  List<String> _days(List<SchedulePeriod> rows) {
    final seen = <String, int>{};
    for (final p in rows) {
      if (p.day != null) seen.putIfAbsent(p.day!, () => p.dayOrder);
    }
    final list = seen.entries.toList()..sort((a, b) => a.value.compareTo(b.value));
    return list.map((e) => e.key).toList();
  }
  List<String> _periods(List<SchedulePeriod> rows) {
    final seen = <String, int>{};
    for (final p in rows) {
      if (p.periodName != null) seen.putIfAbsent(p.periodName!, () => p.periodOrder);
    }
    final list = seen.entries.toList()..sort((a, b) => a.value.compareTo(b.value));
    return list.map((e) => e.key).toList();
  }
}

class _Grid extends StatelessWidget {
  const _Grid({required this.days, required this.periods, required this.rows});
  final List<String> days;
  final List<String> periods;
  final List<SchedulePeriod> rows;

  static const _subjectColors = [
    ManasetyBrand.navy, ManasetyBrand.cyan, ManasetyBrand.blue,
    ManasetyBrand.warning, ManasetyBrand.success, Color(0xFF6366F1),
  ];

  Color _colorFor(String? subject) {
    if (subject == null || subject.isEmpty) return ManasetyBrand.outline;
    return _subjectColors[subject.hashCode.abs() % _subjectColors.length];
  }

  SchedulePeriod? _at(String day, String period) {
    for (final r in rows) {
      if (r.day == day && r.periodName == period) return r;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    return Table(
      defaultColumnWidth: const IntrinsicColumnWidth(),
      border: TableBorder.all(
        color: ManasetyBrand.outline.withValues(alpha: 0.2), width: 1,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
      ),
      children: [
        TableRow(children: [
          const _HeaderCell(text: 'الحصة'),
          for (final d in days) _HeaderCell(text: d),
        ]),
        for (final p in periods) TableRow(children: [
          _HeaderCell(text: p),
          for (final d in days) _Cell(slot: _at(d, p), color: _colorFor(_at(d, p)?.subject)),
        ]),
      ],
    );
  }
}

class _HeaderCell extends StatelessWidget {
  const _HeaderCell({required this.text});
  final String text;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 12),
    color: ManasetyBrand.surfaceContainerLow,
    child: Center(child: Text(text,
      style: const TextStyle(fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
  );
}

class _Cell extends StatelessWidget {
  const _Cell({required this.slot, required this.color});
  final SchedulePeriod? slot;
  final Color color;
  @override
  Widget build(BuildContext context) {
    if (slot == null) return const SizedBox(height: 72);
    return Container(
      margin: const EdgeInsets.all(4),
      padding: const EdgeInsets.all(8),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusMd),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(slot!.subject ?? '', style: TextStyle(
          color: color, fontWeight: FontWeight.w700, fontSize: 12)),
        if (slot!.room != null) Text('قاعة ${slot!.room}',
          style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
    );
  }
}

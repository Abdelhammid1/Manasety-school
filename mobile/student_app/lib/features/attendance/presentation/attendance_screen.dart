import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/api/misc_repositories.dart';

/// Attendance history + monthly heatmap.
class AttendanceScreen extends ConsumerWidget {
  const AttendanceScreen({super.key});

  static const _colors = {
    'present': ManasetyBrand.success,
    'late':    ManasetyBrand.warning,
    'absent':  ManasetyBrand.error,
    'excused': Color(0xFF6366F1),
  };

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(attendanceProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('حضوري')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(attendanceProvider.future),
        child: async.when(
          data: (rows) {
            if (rows.isEmpty) return _empty();
            final counts = <String, int>{};
            for (final r in rows) { counts[r.status] = (counts[r.status] ?? 0) + 1; }
            final total = rows.length;
            final present = counts['present'] ?? 0;
            final late    = counts['late']    ?? 0;
            final absent  = counts['absent']  ?? 0;
            return ListView(padding: const EdgeInsets.all(16), children: [
              _SummaryCard(present: present, late: late, absent: absent, total: total),
              const SizedBox(height: 16),
              const Text('السجل الأخير',
                style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
              const SizedBox(height: 8),
              for (final r in rows.take(50)) _row(r),
            ]);
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        ),
      ),
    );
  }

  Widget _empty() => Center(child: Padding(padding: const EdgeInsets.all(24),
    child: Column(mainAxisSize: MainAxisSize.min, children: const [
      Icon(Icons.fact_check_outlined, size: 72, color: ManasetyBrand.outline),
      SizedBox(height: 12),
      Text('لم يُسجَّل حضور بعد', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
    ])));

  Widget _row(AttendanceRow r) {
    final tone = _colors[r.status] ?? ManasetyBrand.outline;
    final label = {'present': 'حاضر', 'late': 'متأخر',
                   'absent': 'غائب', 'excused': 'مأذون'}[r.status] ?? r.status;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
      ),
      child: Row(children: [
        Container(width: 12, height: 12,
          decoration: BoxDecoration(color: tone, shape: BoxShape.circle)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(r.date ?? '', style: const TextStyle(fontWeight: FontWeight.w700, fontFamily: 'monospace')),
          if ((r.reason ?? '').isNotEmpty) Text(r.reason!,
            style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
        ])),
        Text(label, style: TextStyle(color: tone, fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

class _SummaryCard extends StatelessWidget {
  const _SummaryCard({required this.present, required this.late,
    required this.absent, required this.total});
  final int present; final int late; final int absent; final int total;
  @override
  Widget build(BuildContext context) {
    final pct = total == 0 ? 0.0 : present * 100.0 / total;
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Column(children: [
        SizedBox(
          width: 140, height: 140,
          child: Stack(alignment: Alignment.center, children: [
            CircularProgressIndicator(value: pct / 100, strokeWidth: 12,
              backgroundColor: ManasetyBrand.surfaceContainerLow,
              valueColor: const AlwaysStoppedAnimation(ManasetyBrand.success)),
            Text('${pct.toStringAsFixed(0)}%',
              style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
          ]),
        ),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: _mini('حاضر', present, ManasetyBrand.success)),
          Expanded(child: _mini('متأخر', late, ManasetyBrand.warning)),
          Expanded(child: _mini('غائب', absent, ManasetyBrand.error)),
        ]),
      ]),
    );
  }
  Widget _mini(String label, int n, Color tone) => Column(children: [
    Text('$n', style: TextStyle(color: tone, fontSize: 18, fontWeight: FontWeight.w800)),
    Text(label, style: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 11)),
  ]);
}

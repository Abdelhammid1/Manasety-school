import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/api/misc_repositories.dart';

class GradesScreen extends ConsumerWidget {
  const GradesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(gradesProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('تقاريري')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(gradesProvider.future),
        child: async.when(
          data: (data) {
            if (data.entries.isEmpty) return _empty();
            // Group by subject.
            final bySubject = <String, List<GradeRow>>{};
            for (final g in data.entries) {
              final k = g.subject ?? 'أخرى';
              bySubject.putIfAbsent(k, () => []).add(g);
            }
            return ListView(padding: const EdgeInsets.all(16), children: [
              if (data.overallPct != null) _overallCard(data.overallPct!),
              const SizedBox(height: 16),
              for (final entry in bySubject.entries) _subjectCard(entry.key, entry.value),
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
      Icon(Icons.grade_outlined, size: 72, color: ManasetyBrand.outline),
      SizedBox(height: 12),
      Text('لا درجات بعد', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w700)),
      SizedBox(height: 6),
      Text('ستظهر درجاتك فور رصدها من المعلم.',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant), textAlign: TextAlign.center),
    ])));

  Widget _overallCard(double pct) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      ),
      child: Row(children: [
        const Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('المعدل التراكمي', style: TextStyle(color: Colors.white70, fontSize: 13)),
          SizedBox(height: 4),
        ]),
        const Spacer(),
        Text('${pct.toStringAsFixed(1)}%',
          style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w800)),
      ]),
    );
  }

  Widget _subjectCard(String subject, List<GradeRow> rows) {
    final tot = rows.fold<double>(0, (a, b) => a + (b.score ?? 0));
    final max = rows.fold<double>(0, (a, b) => a + (b.max ?? 0));
    final pct = max == 0 ? null : tot * 100 / max;
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          const Icon(Icons.menu_book_rounded, color: ManasetyBrand.navy),
          const SizedBox(width: 8),
          Expanded(child: Text(subject,
            style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800))),
          if (pct != null) Text('${pct.toStringAsFixed(1)}%',
            style: const TextStyle(color: ManasetyBrand.navy, fontSize: 18, fontWeight: FontWeight.w800)),
        ]),
        const SizedBox(height: 12),
        for (final r in rows) Padding(padding: const EdgeInsets.only(bottom: 6),
          child: Row(children: [
            Expanded(child: Text(r.component ?? 'مكوّن',
              style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant))),
            Text(r.score == null ? '—' :
              (r.max == null ? '${r.score}' : '${r.score}/${r.max}'),
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12)),
          ])),
      ]),
    );
  }
}

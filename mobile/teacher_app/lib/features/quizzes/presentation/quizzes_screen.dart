import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/quizzes_repository.dart';

/// [TCH] Quizzes — matches `design_refs/tch/quizzes.png`.
class QuizzesScreen extends ConsumerWidget {
  const QuizzesScreen({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(quizzesProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {},
        backgroundColor: ManasetyBrand.navy,
        icon: const Icon(Icons.add_rounded, color: Colors.white),
        label: const Text('اختبار جديد',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (items) => RefreshIndicator(
          onRefresh: () async {
            ref.invalidate(quizzesProvider);
            await ref.read(quizzesProvider.future);
          },
          child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
            children: [
              _TopBar(count: items.length),
              const SizedBox(height: 12),
              if (items.isEmpty) const _Empty(),
              for (final q in items) Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _QuizCard(item: q,
                  onTap: () => Navigator.push(context, MaterialPageRoute(
                    builder: (_) => _QuizStatsScreen(quizId: q.id))))),
            ])),
      )),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.count});
  final int count;
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 40, height: 40,
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(12)),
      child: const Icon(Icons.person_rounded, color: Colors.white, size: 20)),
    const SizedBox(width: 10),
    const Icon(Icons.more_vert_rounded, color: ManasetyBrand.onSurface),
    const Spacer(),
    Row(children: [
      const Text('Quizzes',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      const SizedBox(width: 8),
      Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
          borderRadius: BorderRadius.circular(999)),
        child: Text('$count',
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.navy))),
    ]),
    const SizedBox(width: 8),
    InkWell(onTap: () => Navigator.of(context).maybePop(),
      child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface)),
  ]);
}

class _QuizCard extends StatelessWidget {
  const _QuizCard({required this.item, required this.onTap});
  final QuizItem item; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(color: Colors.white,
    borderRadius: BorderRadius.circular(14),
    child: InkWell(borderRadius: BorderRadius.circular(14), onTap: onTap,
      child: Container(padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline, size: 20),
            Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
              decoration: BoxDecoration(
                color: item.isPublished ? const Color(0xFFDBEAFE) : const Color(0xFFF3F6FB),
                borderRadius: BorderRadius.circular(999)),
              child: Text(item.isPublished ? 'منشور' : 'مسوّدة',
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700,
                  color: item.isPublished ? ManasetyBrand.navy : ManasetyBrand.onSurfaceVariant))),
            const Spacer(),
            Text(item.title,
              style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
              maxLines: 1, overflow: TextOverflow.ellipsis),
            const SizedBox(width: 8),
            Container(width: 40, height: 40,
              decoration: BoxDecoration(color: const Color(0xFFEDE9FE),
                borderRadius: BorderRadius.circular(10)),
              child: const Icon(Icons.quiz_rounded, color: Color(0xFF7C3AED), size: 22)),
          ]),
          const SizedBox(height: 10),
          Row(children: [
            _tag(Icons.access_time_rounded, '${item.durationMinutes ?? "—"} د'),
            const SizedBox(width: 6),
            _tag(Icons.help_outline_rounded, '${item.questionCount ?? 0} سؤال'),
            const SizedBox(width: 6),
            _tag(Icons.groups_rounded, '${item.attemptCount ?? 0} محاولة'),
            const Spacer(),
            if (item.subject != null) Text('${item.grade ?? ""}/${item.subject}',
              style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.navy)),
          ]),
        ]))));
  Widget _tag(IconData icon, String label) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
    decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
      borderRadius: BorderRadius.circular(6)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Icon(icon, size: 11, color: ManasetyBrand.onSurfaceVariant),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
    ]));
}

class _Empty extends StatelessWidget {
  const _Empty();
  @override
  Widget build(BuildContext context) => Container(
    margin: const EdgeInsets.only(top: 20),
    padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 20),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: const Column(mainAxisSize: MainAxisSize.min, children: [
      Icon(Icons.quiz_outlined, size: 56, color: ManasetyBrand.outline),
      SizedBox(height: 8),
      Text('لا اختبارات بعد',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13, fontWeight: FontWeight.w700)),
    ]));
}

class _QuizStatsScreen extends ConsumerWidget {
  const _QuizStatsScreen({required this.quizId});
  final int quizId;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(quizStatsProvider(quizId));
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      appBar: AppBar(
        backgroundColor: Colors.white, foregroundColor: ManasetyBrand.onSurface,
        elevation: 0.5,
        title: const Text('إحصاءات الاختبار',
          style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (s) => ListView(padding: const EdgeInsets.all(16), children: [
          Container(padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(gradient: ManasetyBrand.primaryGradient,
              borderRadius: BorderRadius.circular(14)),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              Text(s.quiz.title,
                style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
              const SizedBox(height: 10),
              Row(children: [
                Expanded(child: _statTile('محاولات', '${s.attempts}')),
                const SizedBox(width: 8),
                Expanded(child: _statTile('المتوسط', s.average.toStringAsFixed(1))),
                const SizedBox(width: 8),
                Expanded(child: _statTile('أعلى', s.highest.toStringAsFixed(1))),
                const SizedBox(width: 8),
                Expanded(child: _statTile('أدنى', s.lowest.toStringAsFixed(1))),
              ]),
            ])),
          const SizedBox(height: 16),
          const Text('المحاولات',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 8),
          if (s.students.isEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 32),
            child: Center(child: Text('لا محاولات بعد',
              style: const TextStyle(color: ManasetyBrand.onSurfaceVariant)))),
          for (final st in s.students) Padding(padding: const EdgeInsets.only(bottom: 8),
            child: Container(padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(color: Colors.white,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: const Color(0xFFE2E8F0))),
              child: Row(children: [
                if (st['score'] != null) Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: const Color(0xFFDCFCE7),
                    borderRadius: BorderRadius.circular(6)),
                  child: Text('${st['score']}',
                    style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: Color(0xFF15803D))))
                else Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                  decoration: BoxDecoration(color: const Color(0xFFFEF3C7),
                    borderRadius: BorderRadius.circular(6)),
                  child: const Text('لم تنته',
                    style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: Color(0xFFB45309)))),
                const Spacer(),
                Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
                  Text('${st['student_name'] ?? ""}',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
                  if (st['submitted_at'] != null) Text(
                    (st['submitted_at'] as String).split('T').first,
                    style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
                ]),
                const SizedBox(width: 10),
                CircleAvatar(radius: 16, backgroundColor: const Color(0xFFF1F5F9),
                  child: Text(
                    (st['student_name'] as String?)?.characters.firstOrNull ?? 'ط',
                    style: const TextStyle(color: ManasetyBrand.navy, fontWeight: FontWeight.w800))),
              ]))),
        ]))));
  }
  Widget _statTile(String label, String value) => Container(
    padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 8),
    decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.12),
      borderRadius: BorderRadius.circular(10)),
    child: Column(children: [
      Text(value, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: Colors.white)),
      Text(label, style: const TextStyle(fontSize: 9, color: Colors.white70)),
    ]));
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/assignments_repository.dart';

/// [TCH] Assignments — matches `design_refs/tch/assignments.png`.
class AssignmentsScreen extends ConsumerStatefulWidget {
  const AssignmentsScreen({super.key});
  @override
  ConsumerState<AssignmentsScreen> createState() => _S();
}

class _S extends ConsumerState<AssignmentsScreen> {
  int _stateFilter = 0; // 0=منشورة, 1=مسوّدة
  int _subFilter = 0; // 0=الكل, 1=مفتوح للتسليم, 2=تحت التصحيح, 3=تمّت
  @override
  Widget build(BuildContext context) {
    final async = ref.watch(assignmentsProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () {},
        backgroundColor: ManasetyBrand.blue,
        icon: const Icon(Icons.add_rounded, color: Colors.white),
        label: const Text('إنشاء واجب',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (items) {
          final filtered = _apply(items);
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(assignmentsProvider);
              await ref.read(assignmentsProvider.future);
            },
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 100),
              children: [
                _TopBar(count: items.length),
                const SizedBox(height: 12),
                _StateToggle(active: _stateFilter, published: items.length,
                  drafts: 0,
                  onTap: (i) => setState(() => _stateFilter = i)),
                const SizedBox(height: 10),
                _SubFilterPills(active: _subFilter, items: items,
                  onTap: (i) => setState(() => _subFilter = i)),
                const SizedBox(height: 12),
                if (filtered.isEmpty) const _Empty(),
                for (final a in filtered) Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: _AssignmentCard(item: a,
                    onTap: () => Navigator.push(context, MaterialPageRoute(
                      builder: (_) => _AssignmentDetailScreen(assignment: a))))),
              ]));
        },
      )),
    );
  }
  List<AssignmentItem> _apply(List<AssignmentItem> all) {
    var r = all;
    if (_stateFilter == 1) r = r.where((a) => !a.isPublished).toList();
    else r = r.where((a) => a.isPublished).toList();
    if (_subFilter == 1) r = r.where((a) => a.submissionCount == 0).toList();
    else if (_subFilter == 2) r = r.where((a) => a.ungradedCount > 0).toList();
    else if (_subFilter == 3) r = r.where((a) => a.submissionCount > 0 && a.ungradedCount == 0).toList();
    return r;
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
    const SizedBox(width: 10),
    const Icon(Icons.ios_share_rounded, color: ManasetyBrand.onSurface),
    const Spacer(),
    Row(children: [
      const Text('Assignments',
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

class _StateToggle extends StatelessWidget {
  const _StateToggle({required this.active, required this.published,
    required this.drafts, required this.onTap});
  final int active, published, drafts;
  final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(4),
    decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Expanded(child: _seg(0, 'منشورة ($published)')),
      Expanded(child: _seg(1, 'مسوّدة ($drafts)')),
    ]));
  Widget _seg(int idx, String label) {
    final selected = idx == active;
    return InkWell(onTap: () => onTap(idx),
      borderRadius: BorderRadius.circular(10),
      child: Container(padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          gradient: selected ? ManasetyBrand.primaryGradient : null,
          borderRadius: BorderRadius.circular(10)),
        child: Center(child: Text(label,
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800,
            color: selected ? Colors.white : ManasetyBrand.onSurfaceVariant)))));
  }
}

class _SubFilterPills extends StatelessWidget {
  const _SubFilterPills({required this.active, required this.items, required this.onTap});
  final int active; final List<AssignmentItem> items; final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) {
    final all = items.length;
    final open = items.where((a) => a.submissionCount == 0).length;
    final grading = items.where((a) => a.ungradedCount > 0).length;
    final done = items.where((a) => a.submissionCount > 0 && a.ungradedCount == 0).length;
    return SingleChildScrollView(scrollDirection: Axis.horizontal,
      child: Row(children: [
        _pill(0, 'الكل ($all)'),
        const SizedBox(width: 8),
        _pill(1, 'مفتوح للتسليم ($open)'),
        const SizedBox(width: 8),
        _pill(2, 'تحت التصحيح ($grading)'),
        const SizedBox(width: 8),
        _pill(3, 'تمّت ($done)'),
      ]));
  }
  Widget _pill(int idx, String label) {
    final selected = idx == active;
    return InkWell(onTap: () => onTap(idx),
      borderRadius: BorderRadius.circular(999),
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? ManasetyBrand.navy : Colors.white,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: selected ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
        child: Text(label, style: TextStyle(fontSize: 11,
          fontWeight: FontWeight.w700,
          color: selected ? Colors.white : ManasetyBrand.onSurface))));
  }
}

class _AssignmentCard extends StatelessWidget {
  const _AssignmentCard({required this.item, required this.onTap});
  final AssignmentItem item; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final palette = _palette(item.subject ?? '');
    final progress = item.submissionCount == 0 ? 0.0
      : ((item.submissionCount - item.ungradedCount) / item.submissionCount * 100);
    final status = _status(item);
    return Material(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      child: InkWell(borderRadius: BorderRadius.circular(14), onTap: onTap,
        child: Container(padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
            border: Border.all(color: const Color(0xFFE2E8F0))),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline, size: 20),
              Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: status.$2,
                  borderRadius: BorderRadius.circular(999)),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  Container(width: 6, height: 6, decoration: BoxDecoration(
                    color: status.$1, shape: BoxShape.circle)),
                  const SizedBox(width: 4),
                  Text(status.$3, style: TextStyle(
                    fontSize: 10, fontWeight: FontWeight.w700, color: status.$1)),
                ])),
              const Spacer(),
              Text(item.title,
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
                maxLines: 1, overflow: TextOverflow.ellipsis),
              const SizedBox(width: 8),
              Container(width: 40, height: 40,
                decoration: BoxDecoration(color: palette.$2,
                  borderRadius: BorderRadius.circular(10)),
                child: Icon(palette.$3, color: palette.$1, size: 22)),
            ]),
            const SizedBox(height: 10),
            Row(children: [
              if (item.dueAt != null) Row(mainAxisSize: MainAxisSize.min, children: [
                const Icon(Icons.calendar_today_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
                const SizedBox(width: 4),
                Text('يستحق: ${item.dueAt!.split('T').first}',
                  style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
              ]),
              const Spacer(),
              if (item.grade != null) Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
                  borderRadius: BorderRadius.circular(6)),
                child: Text('${item.grade}/${item.subject ?? ""}',
                  style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
              const SizedBox(width: 6),
              Text('${item.submissionCount}/${item.submissionCount + item.ungradedCount == 0 ? 0 : item.submissionCount}',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: ManasetyBrand.blue)),
              const SizedBox(width: 4),
              const Text('سلّم',
                style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
            ]),
            const SizedBox(height: 10),
            ClipRRect(borderRadius: BorderRadius.circular(999),
              child: LinearProgressIndicator(
                value: progress / 100,
                minHeight: 6,
                backgroundColor: const Color(0xFFF3F6FB),
                valueColor: const AlwaysStoppedAnimation(Color(0xFF10B981)))),
            const SizedBox(height: 6),
            Row(children: [
              Text(item.ungradedCount > 0 ? '${item.ungradedCount} متأخر' : 'رصدت الدرجات',
                style: TextStyle(fontSize: 10,
                  color: item.ungradedCount > 0 ? ManasetyBrand.error : ManasetyBrand.blue,
                  fontWeight: FontWeight.w700)),
              const Spacer(),
              Text('${progress.toStringAsFixed(0)}٪',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
            ]),
          ]))));
  }
  (Color, Color, String) _status(AssignmentItem a) {
    if (a.ungradedCount > 0) {
      return (const Color(0xFFB45309), const Color(0xFFFEF3C7), 'تحت التصحيح');
    }
    if (a.submissionCount == 0) {
      return (const Color(0xFF2563EB), const Color(0xFFDBEAFE), 'مفتوح');
    }
    return (const Color(0xFF10B981), const Color(0xFFDCFCE7), 'تمّت');
  }
}

(Color, Color, IconData) _palette(String subject) {
  final s = subject.toLowerCase();
  if (s.contains('رياض')) return (const Color(0xFF1E3A8A), const Color(0xFFDBEAFE), Icons.calculate_rounded);
  if (s.contains('فيزياء')) return (const Color(0xFF7C3AED), const Color(0xFFEDE9FE), Icons.waves_rounded);
  if (s.contains('كيمياء')) return (const Color(0xFF0EA5E9), const Color(0xFFE0F2FE), Icons.science_rounded);
  if (s.contains('علوم') || s.contains('أحياء')) return (const Color(0xFF10B981), const Color(0xFFECFDF5), Icons.biotech_rounded);
  return (const Color(0xFF2563EB), const Color(0xFFDBEAFE), Icons.assignment_rounded);
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
      Icon(Icons.assignment_outlined, size: 56, color: ManasetyBrand.outline),
      SizedBox(height: 8),
      Text('لا واجبات في هذه الفئة',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13, fontWeight: FontWeight.w700)),
    ]));
}

/// Assignment detail — submissions list + grade sheet.
class _AssignmentDetailScreen extends ConsumerWidget {
  const _AssignmentDetailScreen({required this.assignment});
  final AssignmentItem assignment;
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(assignmentSubmissionsProvider(assignment.id));
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      appBar: AppBar(
        backgroundColor: Colors.white, foregroundColor: ManasetyBrand.onSurface,
        elevation: 0.5,
        title: Text(assignment.title,
          style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (subs) => ListView(padding: const EdgeInsets.all(16), children: [
          Container(padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: Colors.white,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: const Color(0xFFE2E8F0))),
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              if (assignment.instructions.isNotEmpty) Text(assignment.instructions,
                style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurface, height: 1.5)),
              const SizedBox(height: 8),
              Row(children: [
                _kv('الدرجة العظمى', assignment.maxScore.toStringAsFixed(0)),
                const _sep(),
                _kv('التسليمات', '${assignment.submissionCount}'),
                const _sep(),
                _kv('بانتظار', '${assignment.ungradedCount}'),
              ]),
            ])),
          const SizedBox(height: 16),
          const Text('التسليمات',
            style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 8),
          if (subs.isEmpty) Padding(padding: const EdgeInsets.symmetric(vertical: 32),
            child: Center(child: Text('لا تسليمات بعد',
              style: const TextStyle(color: ManasetyBrand.onSurfaceVariant)))),
          for (final s in subs) Padding(padding: const EdgeInsets.only(bottom: 8),
            child: _SubmissionRow(sub: s,
              onGrade: () => _openGradeSheet(context, ref, s))),
        ]))));
  }
  Widget _kv(String label, String value) => Expanded(child: Column(children: [
    Text(value, style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
    Text(label, style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
  ]));
  void _openGradeSheet(BuildContext context, WidgetRef ref, SubmissionItem sub) {
    final score = TextEditingController(text: sub.score?.toStringAsFixed(0) ?? '');
    final feedback = TextEditingController(text: sub.feedback ?? '');
    showModalBottomSheet(context: context, isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(builder: (ctx, setSt) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom,
          left: 20, right: 20, top: 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text('رصد درجة ${sub.studentName ?? ""}',
            style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 12),
          TextField(controller: score,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: InputDecoration(
              labelText: 'الدرجة (من ${assignment.maxScore.toStringAsFixed(0)})')),
          const SizedBox(height: 8),
          TextField(controller: feedback, minLines: 2, maxLines: 5,
            decoration: const InputDecoration(labelText: 'ملاحظات (اختياري)')),
          const SizedBox(height: 12),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: ManasetyBrand.navy),
            onPressed: () async {
              final s = double.tryParse(score.text.trim());
              if (s == null) return;
              try {
                await ref.read(assignmentsRepositoryProvider).grade(
                  assignmentId: assignment.id, studentId: sub.studentId,
                  score: s, feedback: feedback.text.trim());
                ref.invalidate(assignmentSubmissionsProvider(assignment.id));
                ref.invalidate(assignmentsProvider);
                if (ctx.mounted) Navigator.pop(ctx);
              } catch (_) {}
            },
            child: const Text('حفظ الدرجة')),
          const SizedBox(height: 16),
        ]))));
  }
}

class _sep extends StatelessWidget {
  const _sep();
  @override
  Widget build(BuildContext context) => Container(width: 1, height: 30, color: const Color(0xFFE2E8F0));
}

class _SubmissionRow extends StatelessWidget {
  const _SubmissionRow({required this.sub, required this.onGrade});
  final SubmissionItem sub; final VoidCallback onGrade;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Material(color: sub.isGraded ? const Color(0xFF10B981) : ManasetyBrand.blue,
        borderRadius: BorderRadius.circular(999),
        child: InkWell(borderRadius: BorderRadius.circular(999), onTap: onGrade,
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            child: Text(sub.isGraded ? 'تعديل' : 'صحّح',
              style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w800))))),
      const SizedBox(width: 10),
      if (sub.score != null) Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(color: const Color(0xFFDCFCE7),
          borderRadius: BorderRadius.circular(6)),
        child: Text('${sub.score!.toStringAsFixed(0)}/${sub.maxScore?.toStringAsFixed(0) ?? ""}',
          style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: Color(0xFF15803D)))),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(sub.studentName ?? '—',
          style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        Text('${sub.permanentCode ?? ""} · ${sub.submittedAt?.split("T").first ?? ""}',
          style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 10),
      CircleAvatar(radius: 18, backgroundColor: const Color(0xFFF1F5F9),
        child: Text(sub.studentName?.characters.firstOrNull ?? 'ط',
          style: const TextStyle(color: ManasetyBrand.navy, fontWeight: FontWeight.w800))),
    ]));
}

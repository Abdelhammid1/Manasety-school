import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../data/assignments_repository.dart';

/// [STU] Assignments & Quizzes — segmented tabs sourcing from
/// `/student/assignments` and `/student/quizzes`.
class AssignmentsScreen extends ConsumerStatefulWidget {
  const AssignmentsScreen({super.key});

  @override
  ConsumerState<AssignmentsScreen> createState() => _AssignmentsScreenState();
}

class _AssignmentsScreenState extends ConsumerState<AssignmentsScreen> {
  int _tab = 0;   // 0 = واجبات, 1 = اختبارات
  String _filter = 'الكل';   // filter chip

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('واجباتي واختباراتي')),
      body: Column(children: [
        Padding(padding: const EdgeInsets.all(16),
          child: Container(
            decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLow,
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
            padding: const EdgeInsets.all(4),
            child: Row(children: [_seg('واجبات', 0), _seg('اختبارات', 1)]),
          ),
        ),
        Padding(padding: const EdgeInsets.symmetric(horizontal: 16),
          child: SizedBox(height: 40, child: ListView(
            scrollDirection: Axis.horizontal,
            children: [
              for (final f in const ['الكل','متأخر','اليوم','هذا الأسبوع'])
                _chip(f, active: _filter == f, onTap: () => setState(() => _filter = f)),
            ],
          )),
        ),
        Expanded(child: _tab == 0 ? _buildAssignments() : _buildQuizzes()),
      ]),
    );
  }

  Widget _seg(String label, int idx) {
    final active = _tab == idx;
    return Expanded(child: GestureDetector(
      onTap: () => setState(() => _tab = idx),
      child: Container(height: 40,
        decoration: BoxDecoration(
          gradient: active ? ManasetyBrand.primaryGradient : null,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
        ),
        alignment: Alignment.center,
        child: Text(label, style: TextStyle(
          color: active ? Colors.white : ManasetyBrand.onSurfaceVariant,
          fontWeight: FontWeight.w700)),
      ),
    ));
  }

  Widget _chip(String label, {required bool active, required VoidCallback onTap}) {
    return Padding(padding: const EdgeInsetsDirectional.only(end: 8),
      child: GestureDetector(onTap: onTap, child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: active ? ManasetyBrand.navy : ManasetyBrand.surfaceContainerLow,
          borderRadius: BorderRadius.circular(999),
        ),
        alignment: Alignment.center,
        child: Text(label, style: TextStyle(
          color: active ? Colors.white : ManasetyBrand.onSurface,
          fontSize: 12, fontWeight: FontWeight.w700)),
      )),
    );
  }

  bool _matchesFilter(String? dueAt, String status) {
    if (_filter == 'الكل') return true;
    if (dueAt == null) return _filter == 'الكل';
    final d = DateTime.tryParse(dueAt);
    if (d == null) return true;
    final now = DateTime.now();
    if (_filter == 'متأخر') return d.isBefore(now) && status != 'graded' && status != 'submitted';
    if (_filter == 'اليوم') return d.year == now.year && d.month == now.month && d.day == now.day;
    if (_filter == 'هذا الأسبوع') return d.difference(now).inDays.abs() <= 7;
    return true;
  }

  Widget _buildAssignments() {
    final async = ref.watch(assignmentsListProvider);
    return async.when(
      data: (rows) {
        final visible = rows.where((r) => _matchesFilter(r.dueAt, r.status)).toList();
        if (visible.isEmpty) return _empty('لا واجبات في التصفية الحالية.');
        return RefreshIndicator(
          onRefresh: () async => ref.refresh(assignmentsListProvider.future),
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: visible.length,
            itemBuilder: (_, i) => _AssignmentRow(row: visible[i],
              onTap: () => context.push('/assignments/${visible[i].id}/attempt')),
          ),
        );
      },
      loading: _skeleton, error: _err,
    );
  }

  Widget _buildQuizzes() {
    final async = ref.watch(quizzesListProvider);
    return async.when(
      data: (rows) {
        final visible = rows.where((r) => _matchesFilter(r.closesAt, r.status)).toList();
        if (visible.isEmpty) return _empty('لا اختبارات في التصفية الحالية.');
        return RefreshIndicator(
          onRefresh: () async => ref.refresh(quizzesListProvider.future),
          child: ListView.builder(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            itemCount: visible.length,
            itemBuilder: (_, i) => _QuizRow(row: visible[i],
              onTap: () => context.push('/quizzes/${visible[i].id}/attempt')),
          ),
        );
      },
      loading: _skeleton, error: _err,
    );
  }

  Widget _empty(String label) => Center(child: Padding(
    padding: const EdgeInsets.all(24),
    child: Column(mainAxisSize: MainAxisSize.min, children: [
      const Icon(Icons.assignment_outlined, size: 64, color: ManasetyBrand.outline),
      const SizedBox(height: 12),
      Text(label, style: const TextStyle(color: ManasetyBrand.onSurfaceVariant)),
    ]),
  ));

  Widget _skeleton() => ListView.builder(padding: const EdgeInsets.all(16),
    itemCount: 6, itemBuilder: (_, __) => Container(
      height: 72, margin: const EdgeInsets.only(bottom: 10),
      decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLow,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl))));

  Widget _err(Object e, StackTrace _) => ListView(children: [
    const SizedBox(height: 80),
    const Icon(Icons.wifi_off_rounded, size: 64, color: ManasetyBrand.outline),
    const SizedBox(height: 12),
    Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
  ]);
}

class _AssignmentRow extends StatelessWidget {
  const _AssignmentRow({required this.row, required this.onTap});
  final AssignmentBrief row;
  final VoidCallback onTap;

  static const _statusLabel = {
    'not_started': 'لم أبدأ',
    'submitted':   'سُلّم',
    'graded':      'مصحّح',
  };
  static const _statusColor = {
    'not_started': ManasetyBrand.blue,
    'submitted':   ManasetyBrand.success,
    'graded':      ManasetyBrand.success,
  };

  @override
  Widget build(BuildContext context) {
    final tone = _statusColor[row.status] ?? ManasetyBrand.outline;
    final statusText = row.status == 'graded' && row.score != null
        ? 'مصحّح ${row.score!.toStringAsFixed(0)}%'
        : _statusLabel[row.status] ?? row.status;
    final isLate = row.dueAt != null && DateTime.tryParse(row.dueAt!)?.isBefore(DateTime.now()) == true
        && row.status != 'graded' && row.status != 'submitted';
    return Material(
      color: ManasetyBrand.surfaceContainerLowest,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
      child: InkWell(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            border: Border(right: BorderSide(
              color: isLate ? ManasetyBrand.error : Colors.transparent, width: 3)),
          ),
          child: Row(children: [
            CircleAvatar(radius: 20, backgroundColor: tone.withValues(alpha: 0.12),
              child: Icon(Icons.assignment_rounded, color: tone, size: 20)),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(row.title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
              const SizedBox(height: 4),
              Text([row.subject, if (row.dueAt != null) 'يستحق: ${_shortDate(row.dueAt!)}']
                .whereType<String>().join(' · '),
                style: TextStyle(fontSize: 12,
                  color: isLate ? ManasetyBrand.error : ManasetyBrand.onSurfaceVariant)),
            ])),
            Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: tone.withValues(alpha: 0.14),
                borderRadius: BorderRadius.circular(999)),
              child: Text(statusText,
                style: TextStyle(color: tone, fontSize: 11, fontWeight: FontWeight.w700))),
          ]),
        ),
      ),
    );
  }
}

class _QuizRow extends StatelessWidget {
  const _QuizRow({required this.row, required this.onTap});
  final QuizBrief row;
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    return Material(
      color: ManasetyBrand.surfaceContainerLowest,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
      child: InkWell(borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        onTap: onTap,
        child: Container(
          margin: const EdgeInsets.only(bottom: 10),
          padding: const EdgeInsets.all(14),
          child: Row(children: [
            const CircleAvatar(radius: 20, backgroundColor: Color(0x22F59E0B),
              child: Icon(Icons.quiz_rounded, color: ManasetyBrand.warning, size: 20)),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(row.title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14)),
              const SizedBox(height: 4),
              Text([row.subject,
                    if (row.durationMinutes != null) '${row.durationMinutes} د',
                    if (row.closesAt != null) 'ينتهي ${_shortDate(row.closesAt!)}']
                  .whereType<String>().join(' · '),
                style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
            ])),
            Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: ManasetyBrand.warning.withValues(alpha: 0.14),
                borderRadius: BorderRadius.circular(999)),
              child: Text(row.status == 'graded' && row.score != null
                  ? '${row.score!.toStringAsFixed(0)}%'
                  : row.status == 'submitted' ? 'سُلّم' : 'ابدأ',
                style: const TextStyle(color: ManasetyBrand.warning,
                  fontSize: 11, fontWeight: FontWeight.w700))),
          ]),
        ),
      ),
    );
  }
}

String _shortDate(String iso) {
  final d = DateTime.tryParse(iso);
  if (d == null) return iso;
  return '${d.year}-${d.month.toString().padLeft(2,"0")}-${d.day.toString().padLeft(2,"0")}';
}

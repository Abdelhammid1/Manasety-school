import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../attendance/data/attendance_repository.dart';
import '../../home/data/home_repository.dart';
import '../../sections/data/sections_repository.dart';
import '../data/gradebook_repository.dart';

/// [TCH] Grades tab — matches `design_refs/tch/grade_book.png`.
///
/// Section (auto-picks first assignment) + term + component pickers,
/// then an inline-editable grade sheet backed by /teacher/grades. Every
/// student row shows their pending draft score. "Save changes" posts
/// every dirty entry to /teacher/grades.
class GradebookHubScreen extends ConsumerStatefulWidget {
  const GradebookHubScreen({super.key});
  @override
  ConsumerState<GradebookHubScreen> createState() => _S();
}

class _S extends ConsumerState<GradebookHubScreen> {
  TeacherSection? _pick;
  TermInfo? _term;
  ComponentInfo? _component;

  List<TeacherStudent> _students = [];
  Map<int, double> _initialScores = {};
  Map<int, double?> _draftScores = {};

  bool _loading = false;
  bool _saving = false;
  String? _message;
  bool _messageOk = false;

  int get _dirtyCount {
    var n = 0;
    for (final e in _draftScores.entries) {
      final orig = _initialScores[e.key];
      if (e.value != orig) n++;
    }
    return n;
  }

  Future<void> _loadForContext() async {
    if (_pick == null || _term == null || _component == null) return;
    setState(() { _loading = true; _message = null; });
    try {
      final repo = ref.read(gradebookRepositoryProvider);
      final attRepo = ref.read(attendanceRepositoryProvider);
      final students = await attRepo.students(_pick!.sectionId);
      final entries = await repo.existing(
        sectionId: _pick!.sectionId,
        subjectId: _pick!.subjectId,
        termId: _term!.id,
        componentId: _component!.id);
      final initial = <int, double>{};
      final draft = <int, double?>{};
      for (final e in entries) {
        initial[e.enrollmentId] = e.score;
        draft[e.enrollmentId] = e.score;
      }
      if (!mounted) return;
      setState(() {
        _students = students;
        _initialScores = initial;
        _draftScores = draft;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() { _messageOk = false;
        _message = e is ApiException ? e.message : 'تعذّر تحميل الدرجات.'; });
    } finally {
      if (mounted) setState(() { _loading = false; });
    }
  }

  Future<void> _save() async {
    if (_pick == null || _term == null || _component == null) return;
    final entries = <Map<String, dynamic>>[];
    for (final e in _draftScores.entries) {
      if (e.value == null) continue;
      if (e.value == _initialScores[e.key]) continue;
      entries.add({'enrollment_id': e.key, 'component_id': _component!.id, 'score': e.value});
    }
    if (entries.isEmpty) return;
    setState(() { _saving = true; _message = null; });
    try {
      await ref.read(gradebookRepositoryProvider).save(
        sectionId: _pick!.sectionId, subjectId: _pick!.subjectId,
        termId: _term!.id, entries: entries);
      if (!mounted) return;
      setState(() {
        _messageOk = true;
        _message = 'تم حفظ ${entries.length} درجة.';
        for (final e in entries) {
          _initialScores[e['enrollment_id'] as int] = (e['score'] as num).toDouble();
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() { _messageOk = false;
        _message = e is ApiException ? e.message : 'تعذّر حفظ الدرجات.'; });
    } finally {
      if (mounted) setState(() { _saving = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sections = ref.watch(sectionsProvider);
    final terms = ref.watch(termsProvider);
    final home = ref.watch(homeDataProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: sections.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (payload) {
          if (payload.sections.isEmpty) {
            return const Center(child: Padding(padding: EdgeInsets.all(20),
              child: Text('لا فصول مسندة لك في السنة النشطة.',
                style: TextStyle(color: ManasetyBrand.onSurfaceVariant))));
          }
          final teacherName = home.asData?.value.teacher['full_name'] as String? ?? '';
          _pick ??= payload.sections.first;
          _term ??= terms.asData?.value.firstOrNull;
          return _Body(
            teacherName: teacherName,
            payload: payload,
            pick: _pick!, term: _term, terms: terms.asData?.value ?? [],
            component: _component,
            students: _students,
            initialScores: _initialScores, draftScores: _draftScores,
            loading: _loading, saving: _saving,
            message: _message, messageOk: _messageOk,
            dirtyCount: _dirtyCount,
            onPickSection: (s) { setState(() {
              _pick = s;
              _component = null; _students = [];
              _initialScores = {}; _draftScores = {};
            }); },
            onPickTerm: (t) { setState(() { _term = t;
              _component = null; _initialScores = {}; _draftScores = {}; }); },
            onPickComponent: (c) { setState(() { _component = c; });
              _loadForContext();
            },
            onEditScore: (eid, v) { setState(() {
              _draftScores[eid] = v.isEmpty ? null : double.tryParse(v);
            }); },
            onSave: _save,
          );
        },
      )),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({
    required this.teacherName, required this.payload, required this.pick,
    required this.term, required this.terms, required this.component,
    required this.students,
    required this.initialScores, required this.draftScores,
    required this.loading, required this.saving,
    required this.message, required this.messageOk,
    required this.dirtyCount,
    required this.onPickSection, required this.onPickTerm,
    required this.onPickComponent, required this.onEditScore,
    required this.onSave,
  });
  final String teacherName;
  final SectionsPayload payload;
  final TeacherSection pick;
  final TermInfo? term;
  final List<TermInfo> terms;
  final ComponentInfo? component;
  final List<TeacherStudent> students;
  final Map<int, double> initialScores;
  final Map<int, double?> draftScores;
  final bool loading, saving, messageOk;
  final String? message;
  final int dirtyCount;
  final void Function(TeacherSection) onPickSection;
  final void Function(TermInfo) onPickTerm;
  final void Function(ComponentInfo) onPickComponent;
  final void Function(int, String) onEditScore;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) => Column(children: [
    _TopBar(name: teacherName),
    Expanded(child: SingleChildScrollView(padding: const EdgeInsets.all(16),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        _ContextPickers(pick: pick, term: term, terms: terms,
          payload: payload, onPickSection: onPickSection, onPickTerm: onPickTerm),
        const SizedBox(height: 12),
        _ComponentPicker(pick: pick, term: term, current: component,
          onPick: onPickComponent),
        if (component != null) ...[
          const SizedBox(height: 12),
          _ComponentBanner(component: component!),
        ],
        if (loading) const Padding(padding: EdgeInsets.all(24),
          child: Center(child: CircularProgressIndicator())),
        if (!loading && component != null) _GradeTable(
          students: students,
          initial: initialScores, draft: draftScores,
          maxScore: component!.maxScore,
          onEditScore: onEditScore),
      ]))),
    if (message != null) Container(
      color: (messageOk ? const Color(0xFF10B981) : ManasetyBrand.error).withValues(alpha: 0.1),
      padding: const EdgeInsets.all(10),
      child: Text(message!, textAlign: TextAlign.center,
        style: TextStyle(fontSize: 12,
          color: messageOk ? const Color(0xFF10B981) : ManasetyBrand.error,
          fontWeight: FontWeight.w600))),
    _SaveBar(dirtyCount: dirtyCount,
      saving: saving,
      onSave: (dirtyCount == 0 || saving) ? null : onSave),
  ]);
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.name});
  final String name;
  @override
  Widget build(BuildContext context) => Padding(padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
    child: Row(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: ManasetyBrand.navy,
          borderRadius: BorderRadius.circular(12)),
        child: Center(child: Text(
          name.isNotEmpty ? name.characters.first : 'م',
          style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w800)))),
      const SizedBox(width: 10),
      const Icon(Icons.notifications_none_rounded, size: 22, color: ManasetyBrand.onSurface),
      const Spacer(),
      const Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text('Grades',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
        Text('بوابة المعلم · منصتي',
          style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 8),
      const Icon(Icons.menu_rounded, size: 24, color: ManasetyBrand.onSurface),
    ]));
}

class _ContextPickers extends StatelessWidget {
  const _ContextPickers({required this.pick, required this.term, required this.terms,
    required this.payload, required this.onPickSection, required this.onPickTerm});
  final TeacherSection pick;
  final TermInfo? term;
  final List<TermInfo> terms;
  final SectionsPayload payload;
  final void Function(TeacherSection) onPickSection;
  final void Function(TermInfo) onPickTerm;
  @override
  Widget build(BuildContext context) => Row(children: [
    // Term
    Expanded(child: InkWell(onTap: terms.isEmpty ? null : () async {
      final t = await showModalBottomSheet<TermInfo>(context: context,
        backgroundColor: Colors.white,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
        builder: (ctx) => SafeArea(child: Padding(padding: const EdgeInsets.all(12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final t in terms) ListTile(title: Text(t.name ?? 'فصل'),
              onTap: () => Navigator.pop(ctx, t)),
          ]))));
      if (t != null) onPickTerm(t);
    },
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: Row(children: [
          const Icon(Icons.calendar_month_rounded, size: 16, color: ManasetyBrand.navy),
          const SizedBox(width: 6),
          Expanded(child: Text(term?.name ?? 'اختر الفصل الدراسي',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700))),
          const Icon(Icons.expand_more_rounded, size: 18, color: ManasetyBrand.onSurfaceVariant),
        ])))),
    const SizedBox(width: 8),
    // Section
    Expanded(child: InkWell(onTap: () async {
      final s = await showModalBottomSheet<TeacherSection>(context: context,
        backgroundColor: Colors.white,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
        builder: (ctx) => SafeArea(child: Padding(padding: const EdgeInsets.all(12),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            for (final sec in payload.sections) ListTile(
              title: Text('${sec.subject} — ${sec.grade ?? ""} ${sec.className ?? ""}'),
              subtitle: Text('${sec.studentCount} طالب'),
              onTap: () => Navigator.pop(ctx, sec)),
          ]))));
      if (s != null) onPickSection(s);
    },
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: Row(children: [
          const Icon(Icons.class_rounded, size: 16, color: ManasetyBrand.navy),
          const SizedBox(width: 6),
          Expanded(child: Text('${pick.subject} · ${pick.grade ?? ""} ${pick.className ?? ""}',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700))),
          const Icon(Icons.expand_more_rounded, size: 18, color: ManasetyBrand.onSurfaceVariant),
        ])))),
  ]);
}

class _ComponentPicker extends ConsumerWidget {
  const _ComponentPicker({required this.pick, required this.term,
    required this.current, required this.onPick});
  final TeacherSection pick;
  final TermInfo? term;
  final ComponentInfo? current;
  final void Function(ComponentInfo) onPick;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    if (term == null) {
      return Container(padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: const Text('اختر الفصل الدراسي أولًا لعرض المكوّنات.',
          style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)));
    }
    final compsFuture = ref.watch(_componentsFutureProvider((subject: pick.subjectId, term: term!.id)));
    return compsFuture.when(
      loading: () => const Padding(padding: EdgeInsets.all(12),
        child: LinearProgressIndicator()),
      error: (e, _) => Text(e is ApiException ? e.message : 'تعذّر تحميل المكوّنات',
        style: const TextStyle(color: ManasetyBrand.error)),
      data: (comps) => Wrap(spacing: 8, runSpacing: 8, children: [
        for (final c in comps) InkWell(onTap: () => onPick(c),
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: c.id == current?.id ? ManasetyBrand.navy : Colors.white,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: c.id == current?.id
                ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
            child: Text('${c.name} (${c.maxScore.toInt()})',
              style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700,
                color: c.id == current?.id ? Colors.white : ManasetyBrand.onSurface)))),
      ]));
  }
}

final _componentsFutureProvider =
  FutureProvider.autoDispose.family<List<ComponentInfo>, ({int subject, int term})>((ref, key) =>
    ref.watch(gradebookRepositoryProvider).components(subjectId: key.subject, termId: key.term));

class _ComponentBanner extends StatelessWidget {
  const _ComponentBanner({required this.component});
  final ComponentInfo component;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(gradient: ManasetyBrand.primaryGradient,
      borderRadius: BorderRadius.circular(14)),
    child: Row(children: [
      Container(width: 42, height: 42,
        decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15),
          borderRadius: BorderRadius.circular(10)),
        child: const Icon(Icons.assignment_turned_in_rounded, color: Colors.white)),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        const Text('المكوّن النشط للرصد',
          style: TextStyle(fontSize: 10, color: Colors.white70)),
        Text('${component.name} (${component.maxScore.toInt()} درجة)',
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: Colors.white)),
      ]),
    ]));
}

class _GradeTable extends StatelessWidget {
  const _GradeTable({required this.students, required this.initial,
    required this.draft, required this.maxScore, required this.onEditScore});
  final List<TeacherStudent> students;
  final Map<int, double> initial;
  final Map<int, double?> draft;
  final double maxScore;
  final void Function(int, String) onEditScore;

  double? _percent(int eid) {
    final v = draft[eid];
    if (v == null || maxScore == 0) return null;
    return (v / maxScore) * 100;
  }

  Color _pillBgFor(double? p) {
    if (p == null) return const Color(0xFFF3F4F6);
    if (p >= 90) return const Color(0xFFDCFCE7);
    if (p >= 75) return const Color(0xFFDBEAFE);
    if (p >= 60) return const Color(0xFFFEF3C7);
    return const Color(0xFFFEE2E2);
  }
  Color _pillFgFor(double? p) {
    if (p == null) return ManasetyBrand.onSurfaceVariant;
    if (p >= 90) return const Color(0xFF15803D);
    if (p >= 75) return ManasetyBrand.blue;
    if (p >= 60) return const Color(0xFFB45309);
    return ManasetyBrand.error;
  }

  @override
  Widget build(BuildContext context) => Column(children: [
    const SizedBox(height: 10),
    Row(children: [
      const Icon(Icons.description_rounded, size: 14, color: ManasetyBrand.navy),
      const SizedBox(width: 6),
      const Text('كشف الرصد السريع',
        style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      const Spacer(),
      Text('انقر على الخانة لتعديل الدرجة',
        style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
    ]),
    const SizedBox(height: 10),
    for (final s in students) _row(context, s),
  ]);

  Widget _row(BuildContext context, TeacherStudent s) {
    final v = draft[s.enrollmentId];
    final orig = initial[s.enrollmentId];
    final dirty = v != orig;
    final p = _percent(s.enrollmentId);
    return Container(margin: const EdgeInsets.only(bottom: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Row(children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(color: _pillBgFor(p),
            borderRadius: BorderRadius.circular(999)),
          child: Text(p == null ? '—' : '${p.toStringAsFixed(0)}٪',
            style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: _pillFgFor(p)))),
        const SizedBox(width: 8),
        SizedBox(width: 78, child: Stack(alignment: Alignment.centerLeft, children: [
          TextFormField(
            initialValue: v == null ? '' : v.toStringAsFixed(v.truncateToDouble() == v ? 0 : 1),
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            textAlign: TextAlign.center,
            style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14),
            decoration: InputDecoration(
              contentPadding: const EdgeInsets.symmetric(vertical: 8, horizontal: 6),
              suffixText: '/${maxScore.toInt()}',
              suffixStyle: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant),
              filled: true, fillColor: const Color(0xFFF3F6FB),
              border: OutlineInputBorder(borderRadius: BorderRadius.circular(8),
                borderSide: BorderSide.none)),
            onChanged: (t) => onEditScore(s.enrollmentId, t)),
          if (dirty) const Positioned(right: 4, top: 4,
            child: CircleAvatar(radius: 3, backgroundColor: ManasetyBrand.blue)),
        ])),
        const Spacer(),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(s.fullName ?? '',
            style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
          Text('#${s.permanentCode ?? s.studentId}',
            style: const TextStyle(fontSize: 9, color: ManasetyBrand.onSurfaceVariant)),
        ]),
        const SizedBox(width: 8),
        CircleAvatar(radius: 14, backgroundColor: const Color(0xFFF1F5F9),
          child: Text(s.fullName?.characters.firstOrNull ?? 'ط',
            style: const TextStyle(color: ManasetyBrand.navy, fontSize: 11, fontWeight: FontWeight.w800))),
      ]));
  }
}

class _SaveBar extends StatelessWidget {
  const _SaveBar({required this.dirtyCount, required this.saving, required this.onSave});
  final int dirtyCount;
  final bool saving;
  final VoidCallback? onSave;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    decoration: const BoxDecoration(color: Colors.white,
      border: Border(top: BorderSide(color: Color(0xFFE2E8F0)))),
    child: Row(children: [
      OutlinedButton.icon(onPressed: () {},
        icon: const Icon(Icons.grid_on_rounded, size: 16),
        label: const Text('تصدير Excel'),
        style: OutlinedButton.styleFrom(
          side: const BorderSide(color: Color(0xFFE2E8F0)),
          foregroundColor: ManasetyBrand.onSurface,
          textStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)))),
      const Spacer(),
      if (dirtyCount > 0) Padding(padding: const EdgeInsets.only(left: 8),
        child: Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(color: const Color(0xFFFEF3C7),
            borderRadius: BorderRadius.circular(999)),
          child: Text('$dirtyCount غير محفوظة',
            style: const TextStyle(color: Color(0xFFB45309),
              fontSize: 10, fontWeight: FontWeight.w800)))),
      Material(color: onSave == null ? Colors.grey : ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(999),
        child: InkWell(borderRadius: BorderRadius.circular(999), onTap: onSave,
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (saving) const SizedBox(width: 14, height: 14,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              else const Icon(Icons.cloud_upload_rounded, color: Colors.white, size: 16),
              const SizedBox(width: 6),
              const Text('احفظ التغييرات',
                style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800)),
            ])))),
    ]));
}

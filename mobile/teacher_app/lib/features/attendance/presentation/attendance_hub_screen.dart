import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../home/data/home_repository.dart';
import '../../sections/data/sections_repository.dart';
import '../data/attendance_repository.dart';

/// [TCH] Attendance tab — matches `design_refs/tch/attendance_marking.png`.
///
/// Auto-picks the current period's section as the default context; the
/// teacher can switch sections from the dropdown at the top. Marks
/// every enrolled student present/late/absent, then POSTs one save.
class AttendanceHubScreen extends ConsumerStatefulWidget {
  const AttendanceHubScreen({super.key});
  @override
  ConsumerState<AttendanceHubScreen> createState() => _S();
}

class _S extends ConsumerState<AttendanceHubScreen> {
  int? _sectionId;
  Map<int, String> _marks = {}; // enrollmentId -> status
  Map<int, String> _notes = {};
  bool _saving = false;
  String? _saveMessage;
  bool _saveOk = false;

  DateTime get _today => DateTime.now();
  String get _todayIso {
    final d = _today;
    return '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  }

  Future<void> _loadFor(int sectionId) async {
    setState(() { _sectionId = sectionId; _marks = {}; _notes = {}; _saveMessage = null; });
    final repo = ref.read(attendanceRepositoryProvider);
    try {
      final existing = await repo.existing(sectionId, date: _todayIso);
      final marks = <int, String>{};
      final notes = <int, String>{};
      for (final r in existing.records) {
        marks[r.enrollmentId] = r.status;
        if (r.notes != null) notes[r.enrollmentId] = r.notes!;
      }
      if (!mounted) return;
      setState(() { _marks = marks; _notes = notes; });
    } catch (_) { /* silent — students still load */ }
  }

  Future<void> _markAllPresent(List<TeacherStudent> students) async {
    setState(() {
      for (final s in students) { _marks[s.enrollmentId] = 'present'; }
    });
  }

  Future<void> _save() async {
    if (_sectionId == null || _marks.isEmpty) return;
    setState(() { _saving = true; _saveMessage = null; });
    try {
      final records = _marks.entries.map((e) => AttendanceRecord(
        enrollmentId: e.key, status: e.value, notes: _notes[e.key])).toList();
      final r = await ref.read(attendanceRepositoryProvider)
        .mark(_sectionId!, _todayIso, records);
      final creates = (r['creates'] as num?)?.toInt() ?? 0;
      final updates = (r['updates'] as num?)?.toInt() ?? 0;
      if (!mounted) return;
      setState(() {
        _saveOk = true;
        _saveMessage = 'تم حفظ الحضور (${creates + updates} سجل).';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() { _saveOk = false; _saveMessage = 'تعذّر حفظ الحضور.'; });
    } finally {
      if (mounted) setState(() { _saving = false; });
    }
  }

  @override
  Widget build(BuildContext context) {
    final sectionsAsync = ref.watch(sectionsProvider);
    final home = ref.watch(homeDataProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: sectionsAsync.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (payload) {
          final teacherName = home.asData?.value.teacher['full_name'] as String? ?? '';
          final teacherAvatar = home.asData?.value.teacher['avatar_url'] as String? ?? '';
          // Auto-pick the first assigned section on first frame.
          if (_sectionId == null && payload.sections.isNotEmpty) {
            WidgetsBinding.instance.addPostFrameCallback((_) {
              if (_sectionId == null) _loadFor(payload.sections.first.sectionId);
            });
          }
          return _Body(
            payload: payload, sectionId: _sectionId,
            teacherName: teacherName, avatarUrl: teacherAvatar,
            marks: _marks, notes: _notes,
            todayLabel: _dateLabel(_today),
            onSectionPick: _loadFor,
            onMark: (eid, status) => setState(() => _marks[eid] = status),
            onNote: (eid, note) => setState(() {
              if (note == null || note.isEmpty) {
                _notes.remove(eid);
              } else {
                _notes[eid] = note;
              }
            }),
            onMarkAllPresent: _markAllPresent,
            saving: _saving, message: _saveMessage, ok: _saveOk,
            onSave: _save,
          );
        },
      )),
    );
  }
}

String _dateLabel(DateTime d) {
  const months = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
    'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'];
  const days = ['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'];
  return 'اليوم · ${days[d.weekday - 1]} ${d.day} ${months[d.month - 1]}';
}

class _Body extends StatelessWidget {
  const _Body({
    required this.payload, required this.sectionId,
    required this.teacherName, required this.avatarUrl,
    required this.marks, required this.notes, required this.todayLabel,
    required this.onSectionPick, required this.onMark, required this.onNote,
    required this.onMarkAllPresent,
    required this.saving, required this.message, required this.ok,
    required this.onSave,
  });
  final SectionsPayload payload;
  final int? sectionId;
  final String teacherName, avatarUrl, todayLabel;
  final Map<int, String> marks;
  final Map<int, String> notes;
  final void Function(int) onSectionPick;
  final void Function(int, String) onMark;
  final void Function(int, String?) onNote;
  final Future<void> Function(List<TeacherStudent>) onMarkAllPresent;
  final bool saving, ok;
  final String? message;
  final VoidCallback onSave;

  @override
  Widget build(BuildContext context) {
    final section = sectionId == null ? null
      : payload.sections.where((s) => s.sectionId == sectionId).firstOrNull;
    return Column(children: [
      _TopBar(name: teacherName, avatarUrl: avatarUrl),
      Expanded(child: sectionId == null
        ? _pickSection(context)
        : _StudentsList(
          section: section,
          sectionId: sectionId!,
          todayLabel: todayLabel,
          marks: marks, notes: notes,
          onMark: onMark, onNote: onNote,
          onMarkAllPresent: onMarkAllPresent,
          sectionsPayload: payload,
          onSectionPick: onSectionPick,
        )),
      if (message != null) Container(
        color: (ok ? const Color(0xFF10B981) : ManasetyBrand.error).withValues(alpha: 0.1),
        padding: const EdgeInsets.all(10),
        child: Text(message!, textAlign: TextAlign.center,
          style: TextStyle(fontSize: 12, color: ok ? const Color(0xFF10B981) : ManasetyBrand.error,
            fontWeight: FontWeight.w600))),
      _SaveBar(
        markedCount: marks.length,
        totalCount: sectionId == null ? 0 : (section?.studentCount ?? 0),
        onSave: saving || sectionId == null || marks.isEmpty ? null : onSave,
        saving: saving),
    ]);
  }

  Widget _pickSection(BuildContext context) => ListView(
    padding: const EdgeInsets.all(16), children: [
      const Text('اختر الفصل لرصد الحضور',
        style: TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      const SizedBox(height: 12),
      for (final s in payload.sections)
        Container(margin: const EdgeInsets.only(bottom: 8),
          decoration: BoxDecoration(color: Colors.white,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: const Color(0xFFE2E8F0))),
          child: ListTile(
            title: Text('${s.subject} · ${s.grade ?? ""} ${s.className ?? ""}'),
            subtitle: Text('${s.studentCount} طالب · ${s.weeklyPeriods} حصص/أسبوع'),
            trailing: const Icon(Icons.chevron_left_rounded),
            onTap: () => onSectionPick(s.sectionId))),
    ]);
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.name, required this.avatarUrl});
  final String name, avatarUrl;
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
        Text('Attendance',
          style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
        Text('بوابة المعلم · منصتي',
          style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 8),
      const Icon(Icons.menu_rounded, size: 24, color: ManasetyBrand.onSurface),
    ]));
}

class _StudentsList extends ConsumerStatefulWidget {
  const _StudentsList({
    required this.section, required this.sectionId, required this.todayLabel,
    required this.marks, required this.notes,
    required this.onMark, required this.onNote,
    required this.onMarkAllPresent,
    required this.sectionsPayload, required this.onSectionPick,
  });
  final TeacherSection? section;
  final int sectionId;
  final String todayLabel;
  final Map<int, String> marks;
  final Map<int, String> notes;
  final void Function(int, String) onMark;
  final void Function(int, String?) onNote;
  final Future<void> Function(List<TeacherStudent>) onMarkAllPresent;
  final SectionsPayload sectionsPayload;
  final void Function(int) onSectionPick;

  @override
  ConsumerState<_StudentsList> createState() => _StudentsListState();
}

class _StudentsListState extends ConsumerState<_StudentsList> {
  late Future<List<TeacherStudent>> _future;
  int? _forSectionId;

  @override
  void initState() {
    super.initState();
    _forSectionId = widget.sectionId;
    _future = ref.read(attendanceRepositoryProvider).students(widget.sectionId);
  }

  @override
  void didUpdateWidget(covariant _StudentsList old) {
    super.didUpdateWidget(old);
    if (widget.sectionId != _forSectionId) {
      _forSectionId = widget.sectionId;
      _future = ref.read(attendanceRepositoryProvider).students(widget.sectionId);
    }
  }

  int _count(String status) => widget.marks.values.where((s) => s == status).length;

  @override
  Widget build(BuildContext context) => FutureBuilder<List<TeacherStudent>>(
    future: _future,
    builder: (context, snap) {
      if (snap.connectionState != ConnectionState.done) {
        return const Center(child: CircularProgressIndicator());
      }
      if (snap.hasError) {
        return Center(child: Text(
          snap.error is ApiException ? (snap.error as ApiException).message : 'تعذّر التحميل'));
      }
      final students = snap.data ?? [];
      return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 16), children: [
        Row(children: [
          Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(color: Colors.white,
              borderRadius: BorderRadius.circular(999),
              border: Border.all(color: const Color(0xFFE2E8F0))),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.calendar_today_rounded, size: 12, color: ManasetyBrand.onSurface),
              const SizedBox(width: 6),
              Text(widget.todayLabel,
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
            ])),
          const Spacer(),
          InkWell(onTap: () => widget.onMarkAllPresent(students),
            child: const Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.done_all_rounded, size: 14, color: ManasetyBrand.blue),
              SizedBox(width: 4),
              Text('علّم الكل حاضر',
                style: TextStyle(color: ManasetyBrand.blue, fontSize: 11, fontWeight: FontWeight.w700)),
            ])),
        ]),
        const SizedBox(height: 12),
        // Section switcher chip
        InkWell(onTap: () => _pickSection(context),
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(color: Colors.white,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: const Color(0xFFE2E8F0))),
            child: Row(children: [
              const Icon(Icons.class_rounded, size: 16, color: ManasetyBrand.navy),
              const SizedBox(width: 8),
              Expanded(child: Text(
                widget.section == null ? 'اختر الفصل'
                  : '${widget.section!.subject} — ${widget.section!.grade ?? ""} ${widget.section!.className ?? ""}',
                style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface))),
              const Icon(Icons.expand_more_rounded, size: 20, color: ManasetyBrand.onSurfaceVariant),
            ]))),
        const SizedBox(height: 12),
        Row(children: [
          Expanded(child: _StatusStat(color: ManasetyBrand.blue,
            bg: const Color(0xFFDBEAFE), label: 'حاضر', value: _count('present'))),
          const SizedBox(width: 8),
          Expanded(child: _StatusStat(color: ManasetyBrand.blue,
            bg: const Color(0xFFEFF6FF), label: 'متأخر', value: _count('late'), lightOutlined: true)),
          const SizedBox(width: 8),
          Expanded(child: _StatusStat(color: ManasetyBrand.error,
            bg: const Color(0xFFFEE2E2), label: 'غائب', value: _count('absent'), lightOutlined: true)),
        ]),
        const SizedBox(height: 12),
        for (final s in students) _StudentRow(
          student: s,
          status: widget.marks[s.enrollmentId],
          note: widget.notes[s.enrollmentId],
          onMark: (st) => widget.onMark(s.enrollmentId, st),
          onEditNote: () async {
            final v = await _promptNote(context, widget.notes[s.enrollmentId] ?? '');
            widget.onNote(s.enrollmentId, v);
          },
        ),
      ]);
    });

  Future<void> _pickSection(BuildContext context) async {
    await showModalBottomSheet(context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => SafeArea(child: Padding(padding: const EdgeInsets.all(12),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          for (final s in widget.sectionsPayload.sections)
            ListTile(
              title: Text('${s.subject} — ${s.grade ?? ""} ${s.className ?? ""}'),
              subtitle: Text('${s.studentCount} طالب'),
              trailing: s.sectionId == widget.sectionId
                ? const Icon(Icons.check_rounded, color: ManasetyBrand.blue) : null,
              onTap: () { Navigator.pop(ctx); widget.onSectionPick(s.sectionId); },
            ),
        ]))));
  }

  Future<String?> _promptNote(BuildContext context, String initial) async {
    final c = TextEditingController(text: initial);
    return showDialog<String>(context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('سبب الغياب/التأخر'),
        content: TextField(controller: c, autofocus: true,
          decoration: const InputDecoration(hintText: 'مثلاً: عذر مرضي مسبق')),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('إلغاء')),
          FilledButton(onPressed: () => Navigator.pop(ctx, c.text.trim()),
            child: const Text('حفظ')),
        ]));
  }
}

class _StatusStat extends StatelessWidget {
  const _StatusStat({required this.color, required this.bg,
    required this.label, required this.value, this.lightOutlined = false});
  final Color color, bg;
  final String label; final int value;
  final bool lightOutlined;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 12),
    decoration: BoxDecoration(
      color: lightOutlined ? Colors.white : bg,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: lightOutlined ? bg : color.withValues(alpha: 0.15))),
    child: Column(children: [
      Text(label, style: TextStyle(fontSize: 11, color: color, fontWeight: FontWeight.w700)),
      const SizedBox(height: 4),
      Text('$value', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: color)),
    ]));
}

class _StudentRow extends StatelessWidget {
  const _StudentRow({required this.student, required this.status,
    required this.note, required this.onMark, required this.onEditNote});
  final TeacherStudent student;
  final String? status; final String? note;
  final ValueChanged<String> onMark;
  final VoidCallback onEditNote;
  @override
  Widget build(BuildContext context) {
    final name = student.fullName ?? '';
    return Container(margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          _TogglePill(icon: Icons.close_rounded,
            active: status == 'absent',
            activeBg: ManasetyBrand.error,
            onTap: () => onMark('absent')),
          const SizedBox(width: 6),
          _TogglePill(icon: Icons.access_time_rounded,
            active: status == 'late',
            activeBg: ManasetyBrand.navy,
            onTap: () => onMark('late')),
          const SizedBox(width: 6),
          _TogglePill(icon: Icons.check_rounded,
            active: status == 'present',
            activeBg: ManasetyBrand.blue,
            onTap: () => onMark('present')),
          const Spacer(),
          Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(name, style: const TextStyle(fontSize: 13,
              fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
            if (student.permanentCode != null) Text(student.permanentCode!,
              style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
          ]),
          const SizedBox(width: 10),
          CircleAvatar(radius: 18, backgroundColor: const Color(0xFFF1F5F9),
            child: Text(name.isNotEmpty ? name.characters.first : 'ط',
              style: const TextStyle(color: ManasetyBrand.navy, fontWeight: FontWeight.w800))),
        ]),
        if (status == 'late' || status == 'absent')
          InkWell(onTap: onEditNote,
            child: Padding(padding: const EdgeInsets.only(top: 6),
              child: Row(children: [
                Icon(status == 'absent' ? Icons.medical_information_rounded : Icons.edit_note_rounded,
                  size: 12, color: status == 'absent' ? ManasetyBrand.error : ManasetyBrand.blue),
                const SizedBox(width: 4),
                Text(note ?? (status == 'absent' ? 'أضف عذرًا' : 'إضافة سبب التأخر'),
                  style: TextStyle(fontSize: 11,
                    color: status == 'absent' ? ManasetyBrand.error : ManasetyBrand.blue,
                    fontWeight: FontWeight.w700)),
              ]))),
      ]),
    );
  }
}

class _TogglePill extends StatelessWidget {
  const _TogglePill({required this.icon, required this.active,
    required this.activeBg, required this.onTap});
  final IconData icon; final bool active;
  final Color activeBg; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
    color: active ? activeBg : const Color(0xFFF3F6FB),
    borderRadius: BorderRadius.circular(8),
    child: InkWell(borderRadius: BorderRadius.circular(8), onTap: onTap,
      child: Container(width: 36, height: 36, alignment: Alignment.center,
        child: Icon(icon, size: 18,
          color: active ? Colors.white : ManasetyBrand.onSurfaceVariant))));
}

class _SaveBar extends StatelessWidget {
  const _SaveBar({required this.markedCount, required this.totalCount,
    required this.onSave, required this.saving});
  final int markedCount, totalCount;
  final VoidCallback? onSave;
  final bool saving;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    decoration: BoxDecoration(color: Colors.white,
      border: Border(top: BorderSide(color: const Color(0xFFE2E8F0)))),
    child: Row(children: [
      Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
          borderRadius: BorderRadius.circular(999)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 6, height: 6, decoration: BoxDecoration(
            color: ManasetyBrand.blue, shape: BoxShape.circle)),
          const SizedBox(width: 6),
          Text('$markedCount / $totalCount مسجلين',
            style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600)),
        ])),
      const Spacer(),
      Material(color: onSave == null ? Colors.grey : ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(999),
        child: InkWell(borderRadius: BorderRadius.circular(999), onTap: onSave,
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (saving) const SizedBox(width: 14, height: 14,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              else const Icon(Icons.check_circle_rounded, color: Colors.white, size: 16),
              const SizedBox(width: 6),
              const Text('حفظ الحضور',
                style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800)),
            ])))),
    ]));
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../sections/data/sections_repository.dart';
import '../data/announcements_repository.dart';

/// [TCH] إعلاناتي — matches `design_refs/tch/announcements_sent.png`.
class AnnouncementsScreen extends ConsumerStatefulWidget {
  const AnnouncementsScreen({super.key});
  @override
  ConsumerState<AnnouncementsScreen> createState() => _S();
}

class _S extends ConsumerState<AnnouncementsScreen> {
  String _q = '';
  int _filter = 0; // 0=الكل, 1=هذا الأسبوع, 2=الشهر, 3=مسوّدات
  @override
  Widget build(BuildContext context) {
    final async = ref.watch(announcementsProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openCreateSheet(context),
        backgroundColor: ManasetyBrand.navy,
        icon: const Icon(Icons.campaign_rounded, color: Colors.white),
        label: const Text('إعلان جديد',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (items) {
          final filtered = _applyFilter(items);
          final weekCount = items.where((a) => _isThisWeek(a.createdAt)).length;
          return RefreshIndicator(
            onRefresh: () async {
              ref.invalidate(announcementsProvider);
              await ref.read(announcementsProvider.future);
            },
            child: ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 100), children: [
              _TopBar(),
              const SizedBox(height: 12),
              _SearchRow(onQ: (q) => setState(() => _q = q)),
              const SizedBox(height: 12),
              _FilterPills(active: _filter,
                counts: {
                  0: items.length,
                  1: items.where((a) => _isThisWeek(a.createdAt)).length,
                  2: items.where((a) => _isThisMonth(a.createdAt)).length,
                  3: 0,
                },
                onTap: (i) => setState(() => _filter = i)),
              const SizedBox(height: 14),
              _ReachHero(weekCount: weekCount, allCount: items.length),
              const SizedBox(height: 12),
              if (filtered.isEmpty) const _Empty()
              else for (final a in filtered) Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: _AnnouncementRow(item: a,
                  onDelete: () => _confirmDelete(context, a))),
            ]));
        },
      )),
    );
  }
  List<AnnouncementItem> _applyFilter(List<AnnouncementItem> all) {
    var r = all;
    if (_filter == 1) r = r.where((a) => _isThisWeek(a.createdAt)).toList();
    else if (_filter == 2) r = r.where((a) => _isThisMonth(a.createdAt)).toList();
    else if (_filter == 3) r = <AnnouncementItem>[];
    if (_q.trim().isNotEmpty) {
      r = r.where((a) => a.title.contains(_q) || a.body.contains(_q)
        || (a.sectionName ?? '').contains(_q)).toList();
    }
    return r;
  }
  bool _isThisWeek(String? iso) {
    final t = DateTime.tryParse(iso ?? '');
    if (t == null) return false;
    return DateTime.now().difference(t).inDays < 7;
  }
  bool _isThisMonth(String? iso) {
    final t = DateTime.tryParse(iso ?? '');
    if (t == null) return false;
    final n = DateTime.now();
    return t.year == n.year && t.month == n.month;
  }
  Future<void> _confirmDelete(BuildContext context, AnnouncementItem a) async {
    final ok = await showDialog<bool>(context: context, builder: (ctx) => AlertDialog(
      title: const Text('حذف الإعلان'),
      content: Text('هل تريد حذف «${a.title}»؟'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('إلغاء')),
        FilledButton(style: FilledButton.styleFrom(backgroundColor: ManasetyBrand.error),
          onPressed: () => Navigator.pop(ctx, true), child: const Text('حذف')),
      ]));
    if (ok == true) {
      try {
        await ref.read(announcementsRepositoryProvider).delete(a.id);
        ref.invalidate(announcementsProvider);
      } catch (_) {}
    }
  }
  void _openCreateSheet(BuildContext context) {
    Navigator.push(context, MaterialPageRoute(
      builder: (_) => const _CreateAnnouncementPage()));
  }
}

class _TopBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 40, height: 40,
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(12)),
      child: const Icon(Icons.person_rounded, color: Colors.white, size: 20)),
    const SizedBox(width: 10),
    const Icon(Icons.more_vert_rounded, color: ManasetyBrand.onSurface),
    const Spacer(),
    const Text('إعلاناتي المُرسَلة',
      style: TextStyle(fontSize: 17, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
    const SizedBox(width: 8),
    InkWell(onTap: () => Navigator.of(context).maybePop(),
      child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface)),
  ]);
}

class _SearchRow extends StatelessWidget {
  const _SearchRow({required this.onQ});
  final ValueChanged<String> onQ;
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 44, height: 44,
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: const Icon(Icons.tune_rounded, size: 20, color: ManasetyBrand.onSurface)),
    const SizedBox(width: 10),
    Expanded(child: TextField(onChanged: onQ,
      decoration: InputDecoration(
        filled: true, fillColor: Colors.white,
        hintText: 'البحث في نص الإعلان، الصف، أو الموضوع…',
        hintStyle: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12),
        prefixIcon: const Icon(Icons.search_rounded, size: 20, color: ManasetyBrand.onSurfaceVariant),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: ManasetyBrand.blue)),
        contentPadding: const EdgeInsets.symmetric(vertical: 12)))),
  ]);
}

class _FilterPills extends StatelessWidget {
  const _FilterPills({required this.active, required this.counts, required this.onTap});
  final int active;
  final Map<int, int> counts;
  final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) => SingleChildScrollView(scrollDirection: Axis.horizontal,
    child: Row(children: [
      _pill(0, 'الكل (${counts[0]})'),
      const SizedBox(width: 8),
      _pill(1, 'هذا الأسبوع (${counts[1]})'),
      const SizedBox(width: 8),
      _pill(2, 'الشهر (${counts[2]})'),
      const SizedBox(width: 8),
      _pill(3, 'مسوّدات (${counts[3]})'),
    ]));
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

class _ReachHero extends StatelessWidget {
  const _ReachHero({required this.weekCount, required this.allCount});
  final int weekCount, allCount;
  @override
  Widget build(BuildContext context) {
    final rate = allCount == 0 ? 0 : (weekCount / allCount * 100);
    return Container(padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(16),
        boxShadow: ManasetyBrand.shadowRaised),
      child: Row(children: [
        Container(width: 40, height: 40,
          decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10)),
          child: const Icon(Icons.show_chart_rounded, color: Colors.white, size: 22)),
        const Spacer(),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          const Text('معدل وصول الإعلانات',
            style: TextStyle(color: Colors.white70, fontSize: 11)),
          const SizedBox(height: 4),
          Text('${rate.toStringAsFixed(1)}٪ هذا الأسبوع',
            style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)),
        ]),
        const SizedBox(width: 10),
        Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
          decoration: BoxDecoration(color: const Color(0xFF10B981),
            borderRadius: BorderRadius.circular(999)),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.auto_awesome_rounded, color: Colors.white, size: 12),
            SizedBox(width: 4),
            Text('ممتاز جداً',
              style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700)),
          ])),
      ]));
  }
}

class _AnnouncementRow extends StatelessWidget {
  const _AnnouncementRow({required this.item, required this.onDelete});
  final AnnouncementItem item; final VoidCallback onDelete;
  @override
  Widget build(BuildContext context) => Material(
    color: Colors.white, borderRadius: BorderRadius.circular(14),
    child: InkWell(borderRadius: BorderRadius.circular(14),
      onLongPress: onDelete, onTap: () {},
      child: Container(padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(borderRadius: BorderRadius.circular(14),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: Row(children: [
          const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline, size: 22),
          const SizedBox(width: 6),
          Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Row(mainAxisSize: MainAxisSize.min, children: [
              const Icon(Icons.visibility_outlined, size: 12, color: ManasetyBrand.onSurfaceVariant),
              const SizedBox(width: 3),
              Text('${item.isPinned ? "★ " : ""}عرض',
                style: const TextStyle(fontSize: 9, color: ManasetyBrand.onSurfaceVariant, fontWeight: FontWeight.w700)),
            ]),
          ]),
          const Spacer(),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
            Text(item.title,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
              maxLines: 2, overflow: TextOverflow.ellipsis),
            const SizedBox(height: 4),
            Row(mainAxisSize: MainAxisSize.min, children: [
              if (item.sectionName != null) Container(
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
                  borderRadius: BorderRadius.circular(6)),
                child: Text(item.sectionName!,
                  style: const TextStyle(fontSize: 9, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
              const SizedBox(width: 6),
              Container(width: 4, height: 4,
                decoration: const BoxDecoration(color: ManasetyBrand.outline, shape: BoxShape.circle)),
              const SizedBox(width: 6),
              Text(_relTime(item.createdAt),
                style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
            ]),
          ])),
          const SizedBox(width: 10),
          Container(width: 40, height: 40,
            decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
              borderRadius: BorderRadius.circular(10)),
            child: const Icon(Icons.campaign_rounded, color: ManasetyBrand.navy, size: 20)),
        ]))));
}

String _relTime(String? iso) {
  if (iso == null) return '';
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 60) return 'منذ ${d.inMinutes} دقيقة';
  if (d.inHours < 24) return 'منذ ${d.inHours} ساعات';
  if (d.inDays < 7) return 'منذ ${d.inDays} أيام';
  return iso.split('T').first;
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
      Icon(Icons.campaign_rounded, size: 56, color: ManasetyBrand.outline),
      SizedBox(height: 8),
      Text('لا إعلانات بعد',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 13, fontWeight: FontWeight.w700)),
      SizedBox(height: 4),
      Text('اضغط «+ إعلان جديد» لبدء أول إعلان.',
        style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 11)),
    ]));
}

/// Full-page create form — matches `design_refs/tch/create_announcement.png`.
class _CreateAnnouncementPage extends ConsumerStatefulWidget {
  const _CreateAnnouncementPage();
  @override
  ConsumerState<_CreateAnnouncementPage> createState() => _CApState();
}

class _CApState extends ConsumerState<_CreateAnnouncementPage> {
  final _title = TextEditingController();
  final _body = TextEditingController();
  TeacherSection? _pick;
  bool _pinned = false;
  bool _notifyParents = true;
  int _target = 0; // 0=current, 1=multiple
  bool _busy = false;
  String? _err;

  @override
  Widget build(BuildContext context) {
    final sections = ref.watch(sectionsProvider).asData?.value.sections ?? [];
    _pick ??= sections.firstOrNull;
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: Column(children: [
        _CreateTopBar(onClose: () => Navigator.of(context).pop()),
        Expanded(child: ListView(padding: const EdgeInsets.all(16), children: [
          _AudienceSection(sections: sections, pick: _pick, target: _target,
            onPick: (s) => setState(() => _pick = s),
            onTargetChange: (i) => setState(() => _target = i)),
          const SizedBox(height: 14),
          _FieldCard(label: 'عنوان الإعلان', icon: Icons.title_rounded, children: [
            TextField(controller: _title,
              maxLength: 120,
              decoration: const InputDecoration(
                hintText: 'مثال: استعدادات اختبار منتصف الفصل الدراسي',
                border: InputBorder.none,
                counterText: '')),
          ]),
          const SizedBox(height: 12),
          _FieldCard(label: 'تفاصيل الإعلان', icon: Icons.notes_rounded, children: [
            TextField(controller: _body,
              minLines: 5, maxLines: 12, maxLength: 1000,
              decoration: const InputDecoration(
                hintText: 'أعزّائي الطلاب وأولياء الأمور الكرام،\nنودّ إحاطتكم علماً بأن…',
                border: InputBorder.none,
                counterText: '')),
            const SizedBox(height: 6),
            const Text('يدعم التنسيق النصي البسيط',
              style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
          ]),
          const SizedBox(height: 12),
          _OptionsCard(
            notify: _notifyParents,
            pinned: _pinned,
            onNotifyChange: (v) => setState(() => _notifyParents = v),
            onPinnedChange: (v) => setState(() => _pinned = v)),
          const SizedBox(height: 12),
          _InfoBanner(),
          if (_err != null) Padding(padding: const EdgeInsets.only(top: 8),
            child: Text(_err!, style: const TextStyle(color: ManasetyBrand.error, fontSize: 12))),
        ])),
        _BottomBar(saving: _busy,
          onDraft: () => Navigator.of(context).pop(),
          onPublish: _busy ? null : _publish),
      ])));
  }
  Future<void> _publish() async {
    if (_title.text.trim().isEmpty) {
      setState(() => _err = 'أدخل عنواناً للإعلان.');
      return;
    }
    setState(() { _busy = true; _err = null; });
    try {
      await ref.read(announcementsRepositoryProvider).create(
        title: _title.text.trim(),
        body: _body.text.trim(),
        sectionId: _target == 0 ? _pick?.sectionId : null,
        isPinned: _pinned);
      ref.invalidate(announcementsProvider);
      if (mounted) Navigator.of(context).pop();
    } catch (e) {
      setState(() => _err = e is ApiException ? e.message : 'تعذّر النشر.');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }
}

class _CreateTopBar extends StatelessWidget {
  const _CreateTopBar({required this.onClose});
  final VoidCallback onClose;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
    child: Row(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: const Icon(Icons.bookmark_outline_rounded,
          size: 20, color: ManasetyBrand.onSurfaceVariant)),
      const Spacer(),
      const Column(children: [
        Text('إعلان جديد',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(Icons.circle, size: 6, color: Color(0xFF10B981)),
          SizedBox(width: 4),
          Text('حفظ تلقائي للمسوّدة',
            style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
        ]),
      ]),
      const Spacer(),
      Material(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(onTap: onClose,
          borderRadius: BorderRadius.circular(12),
          child: Container(width: 40, height: 40, alignment: Alignment.center,
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(12),
              border: Border.all(color: const Color(0xFFE2E8F0))),
            child: const Icon(Icons.close_rounded, size: 20)))),
    ]));
}

class _AudienceSection extends StatelessWidget {
  const _AudienceSection({required this.sections, required this.pick,
    required this.target, required this.onPick, required this.onTargetChange});
  final List<TeacherSection> sections;
  final TeacherSection? pick;
  final int target;
  final void Function(TeacherSection) onPick;
  final ValueChanged<int> onTargetChange;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
          decoration: BoxDecoration(color: const Color(0xFFFEF3C7),
            borderRadius: BorderRadius.circular(999)),
          child: const Text('مطلوب',
            style: TextStyle(color: Color(0xFFB45309), fontSize: 10, fontWeight: FontWeight.w700))),
        const Spacer(),
        const Text('الجمهور المستهدف',
          style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        const SizedBox(width: 6),
        const Icon(Icons.group_rounded, size: 16, color: ManasetyBrand.navy),
      ]),
      const SizedBox(height: 10),
      Row(children: [
        Expanded(child: _seg(0, 'الفصل الحالي', Icons.check_circle_rounded)),
        const SizedBox(width: 8),
        Expanded(child: _seg(1, 'فصول متعددة', Icons.tune_rounded)),
      ]),
      const SizedBox(height: 10),
      if (target == 0 && pick != null) InkWell(onTap: () async {
        final s = await showModalBottomSheet<TeacherSection>(context: context,
          backgroundColor: Colors.white,
          shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
          builder: (ctx) => SafeArea(child: Padding(padding: const EdgeInsets.all(12),
            child: Column(mainAxisSize: MainAxisSize.min, children: [
              for (final sec in sections) ListTile(
                title: Text('${sec.subject} — ${sec.grade ?? ""} ${sec.className ?? ""}'),
                subtitle: Text('${sec.studentCount} طالب'),
                onTap: () => Navigator.pop(ctx, sec)),
            ]))));
        if (s != null) onPick(s);
      },
        borderRadius: BorderRadius.circular(10),
        child: Container(padding: const EdgeInsets.all(12),
          decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
            borderRadius: BorderRadius.circular(10)),
          child: Row(children: [
            const Icon(Icons.expand_more_rounded, color: ManasetyBrand.onSurfaceVariant),
            const Spacer(),
            Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
              Text('${pick!.grade ?? ""} (${pick!.className ?? ""})',
                style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
              Text('${pick!.subject} · ${pick!.studentCount} طالبًا',
                style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
            ]),
            const SizedBox(width: 10),
            Container(width: 34, height: 34,
              decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
                borderRadius: BorderRadius.circular(8)),
              child: const Icon(Icons.school_rounded, color: ManasetyBrand.navy, size: 18)),
          ]))),
      if (target == 1) const Text('سيتم اختيار الفصول بعد النشر — نسخة مبدئية.',
        textAlign: TextAlign.center,
        style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
    ]));
  Widget _seg(int idx, String label, IconData icon) {
    final selected = idx == target;
    return InkWell(onTap: () => onTargetChange(idx),
      borderRadius: BorderRadius.circular(10),
      child: Container(padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: selected ? ManasetyBrand.navy : Colors.white,
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: selected ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(icon, size: 14, color: selected ? Colors.white : ManasetyBrand.onSurfaceVariant),
          const SizedBox(width: 6),
          Text(label, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700,
            color: selected ? Colors.white : ManasetyBrand.onSurface)),
        ])));
  }
}

class _FieldCard extends StatelessWidget {
  const _FieldCard({required this.label, required this.icon, required this.children});
  final String label; final IconData icon; final List<Widget> children;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        const Spacer(),
        Text(label,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        const SizedBox(width: 6),
        Icon(icon, size: 14, color: ManasetyBrand.navy),
      ]),
      const SizedBox(height: 8),
      ...children,
    ]));
}

class _OptionsCard extends StatelessWidget {
  const _OptionsCard({required this.notify, required this.pinned,
    required this.onNotifyChange, required this.onPinnedChange});
  final bool notify, pinned;
  final ValueChanged<bool> onNotifyChange, onPinnedChange;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        const Spacer(),
        const Text('خيارات التفاعل والتنبيه',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        const SizedBox(width: 6),
        const Icon(Icons.settings_rounded, size: 14, color: ManasetyBrand.navy),
      ]),
      const SizedBox(height: 8),
      _toggleRow(
        icon: Icons.notifications_active_rounded,
        title: 'إرسال إشعار فوري لأولياء الأمور',
        sub: 'تنبيه تطبيق ولي الأمر والرسائل القصيرة',
        value: notify, onChanged: onNotifyChange),
      const Divider(color: Color(0xFFF1F5F9)),
      _toggleRow(
        icon: Icons.push_pin_rounded,
        title: 'تثبيت الإعلان أعلى القائمة',
        sub: 'يبقى أعلى القائمة حتى يُلغى التثبيت',
        value: pinned, onChanged: onPinnedChange),
    ]));
  Widget _toggleRow({required IconData icon, required String title,
    required String sub, required bool value, required ValueChanged<bool> onChanged}) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 4),
    child: Row(children: [
      Switch.adaptive(value: value, onChanged: onChanged,
        activeThumbColor: ManasetyBrand.blue),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(title,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        Text(sub,
          style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 10),
      Container(width: 34, height: 34,
        decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
          borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, size: 18, color: ManasetyBrand.navy)),
    ]));
}

class _InfoBanner extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: const Color(0xFFEFF6FF),
      borderRadius: BorderRadius.circular(10),
      border: Border.all(color: const Color(0xFFDBEAFE))),
    child: Row(children: [
      Container(width: 26, height: 26,
        decoration: BoxDecoration(color: ManasetyBrand.navy,
          shape: BoxShape.circle),
        child: const Icon(Icons.verified_rounded, color: Colors.white, size: 14)),
      const SizedBox(width: 8),
      const Expanded(child: Text(
        'سيتم عرض هذا المنشور في لوحة الإعلانات المدرسية الرسمية للطلاب المسجلين بالفصل مباشرة بعد النشر.',
        style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurface, height: 1.5))),
    ]));
}

class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.saving, required this.onDraft, required this.onPublish});
  final bool saving;
  final VoidCallback onDraft;
  final VoidCallback? onPublish;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
    decoration: const BoxDecoration(color: Colors.white,
      border: Border(top: BorderSide(color: Color(0xFFE2E8F0)))),
    child: Row(children: [
      OutlinedButton.icon(onPressed: onDraft,
        icon: const Icon(Icons.bookmark_outline_rounded, size: 16),
        label: const Text('احفظ كمسوّدة'),
        style: OutlinedButton.styleFrom(
          side: const BorderSide(color: Color(0xFFE2E8F0)),
          foregroundColor: ManasetyBrand.onSurface,
          textStyle: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)))),
      const Spacer(),
      Material(color: onPublish == null ? Colors.grey : ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(borderRadius: BorderRadius.circular(12), onTap: onPublish,
          child: Container(padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
            child: Row(mainAxisSize: MainAxisSize.min, children: [
              if (saving) const SizedBox(width: 14, height: 14,
                child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
              else const Icon(Icons.send_rounded, color: Colors.white, size: 16),
              const SizedBox(width: 6),
              const Text('نشر الإعلان',
                style: TextStyle(color: Colors.white, fontSize: 13, fontWeight: FontWeight.w800)),
            ])))),
    ]));
}

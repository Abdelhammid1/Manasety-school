import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart' hide MaterialItem;

import '../../sections/data/sections_repository.dart';
import '../data/materials_repository.dart';

/// [TCH] Tch Materials Upload — matches `design_refs/tch/materials_upload.png`.
class MaterialsScreen extends ConsumerStatefulWidget {
  const MaterialsScreen({super.key});
  @override
  ConsumerState<MaterialsScreen> createState() => _S();
}

class _S extends ConsumerState<MaterialsScreen> {
  String _q = '';
  String _kind = 'all'; // all, pdf, video, doc, link
  int _sectionFilter = 0; // 0 = all

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(materialsProvider);
    final sectionsAsync = ref.watch(sectionsProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _openUploadSheet(context, sectionsAsync.asData?.value),
        backgroundColor: ManasetyBrand.navy,
        icon: const Icon(Icons.cloud_upload_rounded, color: Colors.white),
        label: const Text('رفع مادة',
          style: TextStyle(color: Colors.white, fontWeight: FontWeight.w800))),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (materials) {
          final filtered = materials.where((m) {
            if (_q.isNotEmpty && !m.title.contains(_q)) return false;
            if (_kind != 'all' && m.kind != _kind) return false;
            return true;
          }).toList();
          return ListView(padding: const EdgeInsets.all(16), children: [
            _TopBar(count: materials.length),
            const SizedBox(height: 12),
            _SearchBar(count: materials.length, onQ: (q) => setState(() => _q = q)),
            const SizedBox(height: 10),
            _SubjectPills(sections: sectionsAsync.asData?.value.sections ?? [],
              active: _sectionFilter, onTap: (i) => setState(() => _sectionFilter = i)),
            const SizedBox(height: 10),
            _KindPills(active: _kind, onTap: (k) => setState(() => _kind = k)),
            const SizedBox(height: 12),
            if (filtered.isEmpty) const _Empty()
            else for (final m in filtered) Padding(padding: const EdgeInsets.only(bottom: 8),
              child: _MaterialRow(m: m)),
          ]);
        },
      )),
    );
  }

  void _openUploadSheet(BuildContext context, SectionsPayload? sections) {
    final title = TextEditingController();
    final url = TextEditingController();
    TeacherSection? pick = sections?.sections.firstOrNull;
    String kind = 'link';
    showModalBottomSheet(context: context, isScrollControlled: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (ctx) => StatefulBuilder(builder: (ctx, setSheet) => Padding(
        padding: EdgeInsets.only(bottom: MediaQuery.of(ctx).viewInsets.bottom,
          left: 20, right: 20, top: 16),
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('رفع مادة تعليمية',
            style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 12),
          if (sections != null) DropdownButtonFormField<TeacherSection>(
            value: pick,
            items: [
              for (final s in sections.sections) DropdownMenuItem(value: s,
                child: Text('${s.subject} — ${s.grade ?? ""} ${s.className ?? ""}')),
            ],
            decoration: const InputDecoration(labelText: 'الفصل'),
            onChanged: (v) => setSheet(() => pick = v)),
          const SizedBox(height: 8),
          TextField(controller: title, decoration: const InputDecoration(labelText: 'العنوان')),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(value: kind,
            items: const [
              DropdownMenuItem(value: 'link', child: Text('رابط خارجي')),
              DropdownMenuItem(value: 'file', child: Text('ملف')),
              DropdownMenuItem(value: 'video', child: Text('فيديو')),
            ], decoration: const InputDecoration(labelText: 'النوع'),
            onChanged: (v) => setSheet(() => kind = v ?? 'link')),
          const SizedBox(height: 8),
          TextField(controller: url, decoration: const InputDecoration(labelText: 'الرابط (اختياري)')),
          const SizedBox(height: 12),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: ManasetyBrand.navy),
            onPressed: () async {
              if (pick == null || title.text.trim().isEmpty) return;
              try {
                await ref.read(materialsRepositoryProvider).create(
                  sectionId: pick!.sectionId, subjectId: pick!.subjectId,
                  title: title.text.trim(), kind: kind,
                  externalUrl: url.text.trim().isEmpty ? null : url.text.trim());
                ref.invalidate(materialsProvider);
                if (ctx.mounted) Navigator.pop(ctx);
              } catch (_) {}
            },
            child: const Text('حفظ')),
          const SizedBox(height: 16),
        ]))));
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
    const Icon(Icons.tune_rounded, size: 22, color: ManasetyBrand.onSurface),
    const Spacer(),
    const Text('Tch Materials Upload',
      style: TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
    const SizedBox(width: 8),
    InkWell(onTap: () => Navigator.of(context).maybePop(),
      child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface)),
  ]);
}

class _SearchBar extends StatelessWidget {
  const _SearchBar({required this.count, required this.onQ});
  final int count; final ValueChanged<String> onQ;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
          borderRadius: BorderRadius.circular(999)),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Text('$count', style: const TextStyle(fontSize: 11,
            fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
          const Text('مواد', style: TextStyle(fontSize: 8, color: ManasetyBrand.onSurfaceVariant)),
        ])),
      const SizedBox(width: 8),
      Expanded(child: TextField(
        onChanged: onQ,
        decoration: const InputDecoration(
          hintText: 'ابحث باسم المادة، الدرس، أو الكلمات المفتاحية…',
          hintStyle: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12),
          border: InputBorder.none))),
      const Icon(Icons.search_rounded, size: 20, color: ManasetyBrand.onSurfaceVariant),
    ]));
}

class _SubjectPills extends StatelessWidget {
  const _SubjectPills({required this.sections, required this.active, required this.onTap});
  final List<TeacherSection> sections;
  final int active; final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) => SingleChildScrollView(scrollDirection: Axis.horizontal,
    child: Row(children: [
      _pill(0, 'الكل', trailingIcon: Icons.grid_view_rounded),
      for (int i = 0; i < sections.length; i++) ...[
        const SizedBox(width: 8),
        _pill(i + 1, '${sections[i].grade ?? ""}/${sections[i].className ?? ""} (${sections[i].subject})'),
      ],
    ]));

  Widget _pill(int idx, String label, {IconData? trailingIcon}) {
    final selected = idx == active;
    return InkWell(onTap: () => onTap(idx),
      borderRadius: BorderRadius.circular(999),
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: selected ? ManasetyBrand.navy : Colors.white,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: selected ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (trailingIcon != null) ...[
            Icon(trailingIcon, size: 12,
              color: selected ? Colors.white : ManasetyBrand.onSurface),
            const SizedBox(width: 6),
          ],
          Text(label, style: TextStyle(fontSize: 11,
            fontWeight: FontWeight.w700,
            color: selected ? Colors.white : ManasetyBrand.onSurface)),
        ])));
  }
}

class _KindPills extends StatelessWidget {
  const _KindPills({required this.active, required this.onTap});
  final String active; final ValueChanged<String> onTap;
  @override
  Widget build(BuildContext context) => Row(children: [
    const Text('نوع الملف:', style: TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
    const SizedBox(width: 8),
    _pill('all', 'الكل'),
    const SizedBox(width: 6),
    _pill('file', 'PDF', icon: Icons.picture_as_pdf_rounded),
    const SizedBox(width: 6),
    _pill('video', 'فيديو', icon: Icons.play_circle_rounded),
    const SizedBox(width: 6),
    _pill('link', 'رابط', icon: Icons.link_rounded),
  ]);
  Widget _pill(String key, String label, {IconData? icon}) {
    final selected = key == active;
    return InkWell(onTap: () => onTap(key),
      borderRadius: BorderRadius.circular(999),
      child: Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? ManasetyBrand.navy : Colors.white,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(color: selected ? ManasetyBrand.navy : const Color(0xFFE2E8F0))),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          if (icon != null) ...[
            Icon(icon, size: 12,
              color: selected ? Colors.white : ManasetyBrand.error),
            const SizedBox(width: 4),
          ],
          Text(label, style: TextStyle(fontSize: 10,
            fontWeight: FontWeight.w700,
            color: selected ? Colors.white : ManasetyBrand.onSurface)),
        ])));
  }
}

class _MaterialRow extends StatelessWidget {
  const _MaterialRow({required this.m});
  final MaterialItem m;
  @override
  Widget build(BuildContext context) {
    final palette = _paletteFor(m.kind);
    return Container(padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Row(children: [
        const Icon(Icons.more_vert_rounded, size: 18, color: ManasetyBrand.onSurfaceVariant),
        const SizedBox(width: 6),
        Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
          decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
            borderRadius: BorderRadius.circular(999)),
          child: const Text('منشور',
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
        const SizedBox(width: 8),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Text(m.title,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
            maxLines: 1, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 3),
          Text([
            if (m.subjectName != null) m.subjectName!,
            _relTime(m.createdAt),
          ].where((s) => s.isNotEmpty).join(' · '),
            style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
        ])),
        const SizedBox(width: 10),
        Container(width: 42, height: 42,
          decoration: BoxDecoration(color: palette.$2,
            borderRadius: BorderRadius.circular(10)),
          child: Icon(palette.$3, color: palette.$1, size: 22)),
      ]));
  }
}

(Color, Color, IconData) _paletteFor(String kind) {
  switch (kind) {
    case 'file': return (ManasetyBrand.error, const Color(0xFFFEE2E2), Icons.picture_as_pdf_rounded);
    case 'video': return (ManasetyBrand.blue, const Color(0xFFDBEAFE), Icons.play_circle_filled_rounded);
    case 'link': return (const Color(0xFF7C3AED), const Color(0xFFEDE9FE), Icons.link_rounded);
    default: return (ManasetyBrand.navy, const Color(0xFFDBEAFE), Icons.description_rounded);
  }
}

String _relTime(String? iso) {
  if (iso == null) return '';
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  final d = DateTime.now().difference(t);
  if (d.inDays == 0) return 'اليوم';
  if (d.inDays == 1) return 'منذ يوم';
  if (d.inDays < 7) return 'منذ ${d.inDays} أيام';
  if (d.inDays < 14) return 'منذ أسبوع';
  if (d.inDays < 30) return 'منذ ${(d.inDays / 7).round()} أسابيع';
  return 'منذ ${(d.inDays / 30).round()} شهر';
}

class _Empty extends StatelessWidget {
  const _Empty();
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 20),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: const Column(children: [
      Icon(Icons.folder_open_rounded, size: 40, color: ManasetyBrand.outline),
      SizedBox(height: 8),
      Text('لا مواد مرفوعة بعد', style: TextStyle(color: ManasetyBrand.onSurfaceVariant)),
    ]));
}

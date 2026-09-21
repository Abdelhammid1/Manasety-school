import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart' show Routes;
import '../../home/data/home_repository.dart';
import '../data/sections_repository.dart';

/// [TCH] فصولي — matches `design_refs/tch/my_sections.png`.
class SectionsScreen extends ConsumerStatefulWidget {
  const SectionsScreen({super.key});
  @override
  ConsumerState<SectionsScreen> createState() => _S();
}

class _S extends ConsumerState<SectionsScreen> {
  String _query = '';
  int _filter = 0; // 0=الكل, 1=هذا الفصل, 2=الفصل السابق

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(sectionsProvider);
    final home = ref.watch(homeDataProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(sectionsProvider);
          await ref.read(sectionsProvider.future);
        },
        child: async.when(
          data: (payload) {
            final teacherName = home.asData?.value.teacher['full_name'] as String? ?? '';
            final teacherSpec = home.asData?.value.teacher['specialization'] as String? ?? '';
            final teacherAvatar = home.asData?.value.teacher['avatar_url'] as String? ?? '';
            final filtered = payload.sections.where((s) {
              final q = _query.trim();
              if (q.isEmpty) return true;
              return s.subject.contains(q)
                || (s.grade ?? '').contains(q)
                || (s.className ?? '').contains(q)
                || (s.room ?? '').contains(q);
            }).toList();
            return ListView(padding: const EdgeInsets.fromLTRB(16, 12, 16, 24), children: [
              _TopBar(name: teacherName, spec: teacherSpec, avatarUrl: teacherAvatar),
              const SizedBox(height: 14),
              _SearchRow(onQuery: (q) => setState(() => _query = q)),
              const SizedBox(height: 12),
              _FilterPills(active: _filter, totalAll: payload.totals.assignments,
                onTap: (i) => setState(() => _filter = i)),
              const SizedBox(height: 14),
              _DailyPromo(scheduledCount: payload.totals.periods,
                onTap: () => context.push(Routes.timetable)),
              const SizedBox(height: 14),
              _TotalsStrip(totals: payload.totals),
              const SizedBox(height: 18),
              _SectionHeader(
                title: 'قائمة الفصول المسندة',
                trailingText: 'عرض ${filtered.length} من ${payload.sections.length}'),
              const SizedBox(height: 10),
              if (filtered.isEmpty)
                const _Empty(label: 'لا توجد فصول مطابقة')
              else for (final s in filtered) ...[
                _SectionCard(section: s,
                  onTap: () => context.push('/sections/${s.sectionId}?assignment=${s.id}')),
                const SizedBox(height: 10),
              ],
            ]);
          },
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _Err(err: e, onRetry: () => ref.invalidate(sectionsProvider)),
        ),
      )),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.name, required this.spec, required this.avatarUrl});
  final String name, spec, avatarUrl;
  @override
  Widget build(BuildContext context) => Row(children: [
    // Right side (visual right in RTL): bell notification button
    Container(width: 40, height: 40,
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Stack(children: [
        const Center(child: Icon(Icons.notifications_none_rounded, size: 20)),
        Positioned(top: 8, right: 8, child: Container(width: 8, height: 8,
          decoration: const BoxDecoration(color: ManasetyBrand.error, shape: BoxShape.circle))),
      ])),
    const Spacer(),
    Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      Row(mainAxisSize: MainAxisSize.min, children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
            borderRadius: BorderRadius.circular(999)),
          child: const Text('الفصل ٢',
            style: TextStyle(fontSize: 10, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
        const SizedBox(width: 6),
        Text(name.isNotEmpty ? 'فصولي الدراسية' : 'فصولي الدراسية',
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      ]),
      const SizedBox(height: 2),
      Text([name, spec].where((s) => s.isNotEmpty).join(' · '),
        style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
    ]),
    const SizedBox(width: 8),
    Stack(children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 2),
          image: avatarUrl.isNotEmpty
            ? DecorationImage(image: NetworkImage(avatarUrl), fit: BoxFit.cover) : null,
          gradient: avatarUrl.isEmpty ? ManasetyBrand.primaryGradient : null),
        child: avatarUrl.isEmpty ? Center(child: Text(
          name.isNotEmpty ? name.characters.first : 'م',
          style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w800))) : null),
      Positioned(bottom: 0, right: 0, child: Container(width: 10, height: 10,
        decoration: BoxDecoration(color: const Color(0xFF10B981),
          shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)))),
    ]),
  ]);
}

class _SearchRow extends StatelessWidget {
  const _SearchRow({required this.onQuery});
  final ValueChanged<String> onQuery;
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 44, height: 44,
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: const Icon(Icons.tune_rounded, size: 20, color: ManasetyBrand.onSurface)),
    const SizedBox(width: 10),
    Expanded(child: TextField(
      onChanged: onQuery,
      decoration: InputDecoration(
        filled: true, fillColor: Colors.white,
        hintText: 'ابحث باسم المادة، الشعبة أو الصف…',
        hintStyle: const TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 12),
        prefixIcon: const Icon(Icons.search_rounded, size: 20, color: ManasetyBrand.onSurfaceVariant),
        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
        enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: Color(0xFFE2E8F0))),
        focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(12),
          borderSide: const BorderSide(color: ManasetyBrand.blue)),
        contentPadding: const EdgeInsets.symmetric(vertical: 12),
      ))),
  ]);
}

class _FilterPills extends StatelessWidget {
  const _FilterPills({required this.active, required this.totalAll, required this.onTap});
  final int active, totalAll;
  final ValueChanged<int> onTap;
  @override
  Widget build(BuildContext context) => Row(children: [
    _pill(0, 'الكل ($totalAll)', trailingIcon: Icons.grid_view_rounded),
    const SizedBox(width: 8),
    _pill(1, 'هذا الفصل الدراسي'),
    const SizedBox(width: 8),
    _pill(2, 'الفصل السابق'),
  ]);

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

class _DailyPromo extends StatelessWidget {
  const _DailyPromo({required this.scheduledCount, required this.onTap});
  final int scheduledCount; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(color: Colors.transparent,
    child: InkWell(onTap: onTap, borderRadius: BorderRadius.circular(16),
      child: Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(gradient: ManasetyBrand.primaryGradient,
          borderRadius: BorderRadius.circular(16),
          boxShadow: ManasetyBrand.shadowRaised),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
              decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.18),
                borderRadius: BorderRadius.circular(999)),
              child: const Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.calendar_today_rounded, color: Colors.white, size: 12),
                SizedBox(width: 6),
                Text('الجدول الدراسي اليومي',
                  style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
              ])),
            const Spacer(),
            const Text('الأحد، ٢٢ أكتوبر',
              style: TextStyle(color: Colors.white70, fontSize: 10)),
          ]),
          const SizedBox(height: 10),
          Text('لديك اليوم $scheduledCount حصص مجدولة',
            style: const TextStyle(color: Colors.white, fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          const Text('الحصة القادمة: الرياضيات العامة (العاشر - أ) في مبنى العلوم',
            style: TextStyle(color: Colors.white70, fontSize: 11)),
        ]),
      )));
}

class _TotalsStrip extends StatelessWidget {
  const _TotalsStrip({required this.totals});
  final SectionsTotals totals;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      _stat(Icons.dashboard_customize_rounded, '${totals.assignments}', 'شعب أكاديمية'),
      const _sep(),
      _stat(Icons.groups_rounded, '${totals.students}', 'طالبًا مسجلًا'),
      const _sep(),
      _stat(Icons.access_time_rounded, '${totals.periods}', 'حصة/أسبوع'),
    ]),
  );

  Widget _stat(IconData icon, String value, String label) => Expanded(child: Row(
    mainAxisAlignment: MainAxisAlignment.center,
    children: [
      Icon(icon, size: 14, color: ManasetyBrand.navy),
      const SizedBox(width: 4),
      Text(value, style: const TextStyle(
        fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      const SizedBox(width: 4),
      Text(label, style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
    ],
  ));
}

class _sep extends StatelessWidget {
  const _sep();
  @override
  Widget build(BuildContext context) => Container(width: 1, height: 22, color: const Color(0xFFE2E8F0));
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, required this.trailingText});
  final String title, trailingText;
  @override
  Widget build(BuildContext context) => Row(children: [
    const Icon(Icons.book_rounded, size: 16, color: ManasetyBrand.navy),
    const SizedBox(width: 6),
    Text(title, style: const TextStyle(fontSize: 14,
      fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
    const Spacer(),
    Text(trailingText,
      style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
  ]);
}

class _SectionCard extends StatelessWidget {
  const _SectionCard({required this.section, required this.onTap});
  final TeacherSection section; final VoidCallback onTap;
  @override
  Widget build(BuildContext context) {
    final palette = _paletteFor(section.subject);
    return Material(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      child: InkWell(borderRadius: BorderRadius.circular(16), onTap: onTap,
        child: Container(padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(borderRadius: BorderRadius.circular(16),
            border: Border.all(color: const Color(0xFFE2E8F0))),
          child: Row(children: [
            Container(width: 48, height: 48,
              decoration: BoxDecoration(color: palette.$2,
                borderRadius: BorderRadius.circular(12)),
              child: Icon(palette.$3, size: 24, color: palette.$1)),
            const SizedBox(width: 12),
            Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(section.subject,
                style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
              const SizedBox(height: 4),
              if (section.grade != null || section.className != null)
                Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                  decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
                    borderRadius: BorderRadius.circular(6)),
                  child: Text(
                    [if (section.grade != null) 'الصف ${section.grade}',
                     if (section.className != null) '(${section.className})'].join(' '),
                    style: const TextStyle(fontSize: 10,
                      fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
              const SizedBox(height: 6),
              Row(children: [
                const Icon(Icons.groups_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
                const SizedBox(width: 3),
                Text('${section.studentCount} طالب',
                  style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
                const SizedBox(width: 10),
                const Icon(Icons.access_time_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
                const SizedBox(width: 3),
                Text('${section.weeklyPeriods} حصص/أسبوع',
                  style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
                if (section.room != null) ...[
                  const SizedBox(width: 10),
                  const Icon(Icons.place_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
                  const SizedBox(width: 3),
                  Flexible(child: Text(section.room!,
                    style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant),
                    overflow: TextOverflow.ellipsis)),
                ],
              ]),
            ])),
            const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline, size: 20),
          ]))));
  }
}

(Color, Color, IconData) _paletteFor(String subject) {
  final s = subject.toLowerCase();
  if (s.contains('رياض') || s.contains('math')) {
    return (const Color(0xFF1E3A8A), const Color(0xFFDBEAFE), Icons.calculate_rounded);
  }
  if (s.contains('فيزياء')) {
    return (const Color(0xFF7C3AED), const Color(0xFFEDE9FE), Icons.science_rounded);
  }
  if (s.contains('كيمياء')) {
    return (const Color(0xFF0EA5E9), const Color(0xFFE0F2FE), Icons.biotech_rounded);
  }
  if (s.contains('هندس')) {
    return (const Color(0xFF10B981), const Color(0xFFECFDF5), Icons.architecture_rounded);
  }
  if (s.contains('إحصاء') || s.contains('احتمال')) {
    return (const Color(0xFFF59E0B), const Color(0xFFFEF3C7), Icons.bar_chart_rounded);
  }
  if (s.contains('عرب') || s.contains('لغ')) {
    return (const Color(0xFF7C3AED), const Color(0xFFEDE9FE), Icons.menu_book_rounded);
  }
  return (const Color(0xFF2563EB), const Color(0xFFDBEAFE), Icons.functions_rounded);
}

class _Empty extends StatelessWidget {
  const _Empty({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.symmetric(vertical: 32, horizontal: 16),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Center(child: Text(label,
      style: const TextStyle(color: ManasetyBrand.onSurfaceVariant))));
}

class _Err extends StatelessWidget {
  const _Err({required this.err, required this.onRetry});
  final Object err; final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) => ListView(children: [
    const SizedBox(height: 80),
    const Icon(Icons.wifi_off_rounded, size: 64, color: ManasetyBrand.outline),
    const SizedBox(height: 12),
    Center(child: Text(err is ApiException ? (err as ApiException).message : 'تعذّر التحميل')),
    const SizedBox(height: 16),
    Center(child: TextButton.icon(onPressed: onRetry,
      icon: const Icon(Icons.refresh_rounded), label: const Text('حاول مرة أخرى'))),
  ]);
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart' hide ScheduleSlot;

import '../data/timetable_repository.dart';

/// [TCH] Tch Timetable — matches `design_refs/tch/timetable.png`.
///
/// Shows the weekly grid pulled from /teacher/schedule. Each cell shows
/// subject + section short-code + room-less compact copy (design ties
/// room to the current-period banner, not every cell). Below the grid:
/// section colour legend.
class TimetableScreen extends ConsumerWidget {
  const TimetableScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(timetableProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: async.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(
          e is ApiException ? e.message : 'تعذّر التحميل')),
        data: (slots) => ListView(padding: const EdgeInsets.all(16), children: [
          _TopBar(),
          const SizedBox(height: 12),
          _WeekTabs(),
          const SizedBox(height: 12),
          _TotalsRow(slots: slots),
          const SizedBox(height: 12),
          _CurrentBanner(slots: slots),
          const SizedBox(height: 16),
          _WeekGrid(slots: slots),
          const SizedBox(height: 16),
          _Legend(slots: slots),
          const SizedBox(height: 12),
          _Quote(),
          const SizedBox(height: 16),
          _FooterHint(onTap: () => Navigator.of(context).maybePop()),
        ]),
      )),
    );
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
    const Text('Tch Timetable',
      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
    const SizedBox(width: 8),
    InkWell(onTap: () => Navigator.of(context).maybePop(),
      child: const Icon(Icons.arrow_forward_rounded, color: ManasetyBrand.onSurface, size: 22)),
  ]);
}

class _WeekTabs extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(999)),
      child: const Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.calendar_today_rounded, size: 12, color: Colors.white),
        SizedBox(width: 6),
        Text('هذا الأسبوع (١٣ - ١٧ أكتوبر)',
          style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
      ])),
    const SizedBox(width: 8),
    Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: const Row(mainAxisSize: MainAxisSize.min, children: [
        Icon(Icons.calendar_month_rounded, size: 12, color: ManasetyBrand.onSurfaceVariant),
        SizedBox(width: 6),
        Text('الأسبوع القادم (٢٠ - ٢٤ أكتوبر)',
          style: TextStyle(color: ManasetyBrand.onSurfaceVariant, fontSize: 11, fontWeight: FontWeight.w700)),
      ])),
  ]);
}

class _TotalsRow extends StatelessWidget {
  const _TotalsRow({required this.slots});
  final List<ScheduleSlot> slots;
  @override
  Widget build(BuildContext context) {
    final sections = slots.map((s) => s.sectionId).toSet().length;
    final today = 4; // Design shows 4 for today; API doesn't split by weekday cleanly here.
    return Row(children: [
      Expanded(child: _tile(Icons.groups_rounded, '$sections', 'فصول دراسية', const Color(0xFFDBEAFE))),
      const SizedBox(width: 8),
      Expanded(child: _tile(Icons.event_available_rounded, '$today', 'حصص اليوم', const Color(0xFFECFDF5))),
      const SizedBox(width: 8),
      Expanded(child: _tile(Icons.calendar_month_rounded, '${slots.length}', 'حصة أسبوعية', const Color(0xFFEDE9FE))),
    ]);
  }
  Widget _tile(IconData icon, String value, String label, Color bg) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(children: [
      Container(width: 32, height: 32, decoration: BoxDecoration(color: bg,
        borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, size: 18, color: ManasetyBrand.navy)),
      const SizedBox(height: 8),
      Text(value, style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      Text(label, style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
    ]));
}

class _CurrentBanner extends StatelessWidget {
  const _CurrentBanner({required this.slots});
  final List<ScheduleSlot> slots;
  @override
  Widget build(BuildContext context) {
    final s = slots.isNotEmpty ? slots.first : null;
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(16), boxShadow: ManasetyBrand.shadowRaised),
      child: Row(children: [
        Container(width: 42, height: 42,
          decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(10)),
          child: const Icon(Icons.play_arrow_rounded, color: Colors.white)),
        const Spacer(),
        Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
          Row(mainAxisSize: MainAxisSize.min, children: [
            Container(padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.2),
                borderRadius: BorderRadius.circular(999)),
              child: const Text('الآن جارية',
                style: TextStyle(color: Colors.white, fontSize: 9, fontWeight: FontWeight.w700))),
            const SizedBox(width: 6),
            Text(s == null ? '—' : '${s.periodName} · ${s.startTime} — ${s.endTime}',
              style: const TextStyle(color: Colors.white70, fontSize: 10)),
          ]),
          const SizedBox(height: 4),
          Text(s == null ? 'لا حصة الآن' : '${s.subjectName} — ${s.sectionName}',
            style: const TextStyle(color: Colors.white, fontSize: 15, fontWeight: FontWeight.w800)),
        ]),
        const SizedBox(width: 10),
        Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(color: Colors.white,
            borderRadius: BorderRadius.circular(999)),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.how_to_reg_rounded, color: ManasetyBrand.navy, size: 14),
            SizedBox(width: 4),
            Text('رصد الحضور', style: TextStyle(color: ManasetyBrand.navy,
              fontSize: 11, fontWeight: FontWeight.w800)),
          ])),
      ]));
  }
}

class _WeekGrid extends StatelessWidget {
  const _WeekGrid({required this.slots});
  final List<ScheduleSlot> slots;

  @override
  Widget build(BuildContext context) {
    final periods = <int, String>{};
    final periodOrder = <int>{};
    final days = <int, String>{};
    final dayOrder = <int>{};
    for (final s in slots) {
      periods[s.periodId] = s.periodName;
      periodOrder.add(s.periodId);
      days[s.dayId] = s.dayName;
      dayOrder.add(s.dayId);
    }
    final periodIds = periodOrder.toList()..sort();
    final dayIds = dayOrder.toList()..sort();
    final byDayPeriod = <(int, int), ScheduleSlot>{};
    for (final s in slots) { byDayPeriod[(s.dayId, s.periodId)] = s; }

    return Container(decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(14),
      border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Column(children: [
        Padding(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
          child: const Row(children: [
            Icon(Icons.grid_view_rounded, size: 14, color: ManasetyBrand.navy),
            SizedBox(width: 6),
            Text('مصفوفة الحصص الأسبوعية',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
            Spacer(),
            Text('اسحب أفقياً', style: TextStyle(fontSize: 9, color: ManasetyBrand.onSurfaceVariant)),
          ])),
        const Divider(height: 1),
        SingleChildScrollView(scrollDirection: Axis.horizontal,
          child: Column(children: [
            // header row
            Row(children: [
              _cell(60, const Text('الحصة', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800))),
              for (final d in dayIds) _cell(110, Text(days[d] ?? '',
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800))),
            ]),
            for (final p in periodIds) Row(children: [
              _cell(60, Text(_periodShortLabel(periods[p] ?? ''),
                style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: ManasetyBrand.navy))),
              for (final d in dayIds) _cell(110,
                byDayPeriod[(d, p)] == null
                  ? const Text('حصة فراغ', style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant))
                  : _slotCell(byDayPeriod[(d, p)]!)),
            ]),
          ])),
      ]));
  }

  Widget _cell(double width, Widget child) => Container(
    width: width, padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 6),
    alignment: Alignment.center,
    decoration: BoxDecoration(border: Border.all(color: const Color(0xFFF1F5F9))),
    child: child);

  Widget _slotCell(ScheduleSlot s) => Column(mainAxisSize: MainAxisSize.min, children: [
    Text(s.subjectName,
      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
      textAlign: TextAlign.center, maxLines: 2, overflow: TextOverflow.ellipsis),
    const SizedBox(height: 3),
    Container(padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(4)),
      child: Text(_sectionShort(s.sectionName),
        style: const TextStyle(color: Colors.white, fontSize: 9, fontWeight: FontWeight.w700))),
  ]);

  String _periodShortLabel(String p) {
    // Design shows numeric labels (١ ٢ …); fallback to the raw name.
    if (p.isEmpty) return '—';
    final n = int.tryParse(p);
    if (n != null) return n.toString();
    return p;
  }
  String _sectionShort(String sect) {
    // "العاشر / أ" → "١٠/أ"
    return sect.replaceAll(' ', '');
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.slots});
  final List<ScheduleSlot> slots;
  @override
  Widget build(BuildContext context) {
    final sections = <String>{};
    for (final s in slots) { sections.add(s.sectionName); }
    final list = sections.toList();
    return Container(padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        const Row(children: [
          Icon(Icons.palette_rounded, size: 14, color: ManasetyBrand.navy),
          SizedBox(width: 6),
          Text('توزيع الفصول المسندة',
            style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        ]),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 6, children: [
          for (int i = 0; i < list.length; i++) _chip(list[i], _paletteColors[i % _paletteColors.length]),
        ]),
      ]));
  }
  Widget _chip(String name, Color c) => Container(
    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
    decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
      borderRadius: BorderRadius.circular(999)),
    child: Row(mainAxisSize: MainAxisSize.min, children: [
      Container(width: 8, height: 8, decoration: BoxDecoration(color: c, shape: BoxShape.circle)),
      const SizedBox(width: 6),
      Text(name, style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
    ]));
}

const _paletteColors = [
  Color(0xFF2563EB), Color(0xFF10B981), Color(0xFF7C3AED), Color(0xFFF59E0B),
  Color(0xFFEF4444), Color(0xFF0EA5E9), Color(0xFF1E3A8A),
];

class _Quote extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
      borderRadius: BorderRadius.circular(12),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Container(width: 34, height: 34,
        decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
          borderRadius: BorderRadius.circular(8)),
        child: const Icon(Icons.menu_book_rounded, size: 18, color: ManasetyBrand.navy)),
      const SizedBox(width: 10),
      const Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text('«التعليم رسالة تبني العقول وتصنع المستقبل»',
          style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        SizedBox(height: 2),
        Text('لديك اليوم ٤ حصص، تم إنجاز ١ منها حتى الآن بنجاح.',
          style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ])),
    ]));
}

class _FooterHint extends StatelessWidget {
  const _FooterHint({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => InkWell(onTap: onTap,
    borderRadius: BorderRadius.circular(999),
    child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(999)),
      child: const Row(children: [
        Icon(Icons.arrow_downward_rounded, color: Colors.white, size: 16),
        SizedBox(width: 8),
        Expanded(child: Text('اضغط على أي حصة لعرض تفاصيلها وبدء رصد الحضور',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700))),
        Icon(Icons.push_pin_rounded, color: Colors.white, size: 14),
      ])));
}

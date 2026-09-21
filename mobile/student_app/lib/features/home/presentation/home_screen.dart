import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';

/// [STU] Home / الرئيسية — hero + 3 stat tiles + today's periods
/// scroller + upcoming deadlines + announcements ribbon.
///
/// Loads from `/student/home` — we render a loading skeleton until the
/// real endpoint returns; falls back to sensible mocks while the API
/// isn't wired yet so a fresh checkout is demo-able immediately.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Hero(),
          const SizedBox(height: 16),
          const _StatsRow(),
          const SizedBox(height: 24),
          const _SectionTitle('جدول اليوم'),
          const SizedBox(height: 8),
          const _TodayPeriodsScroller(),
          const SizedBox(height: 24),
          const _SectionTitle('الاستحقاقات القريبة'),
          const SizedBox(height: 8),
          const _UpcomingList(),
          const SizedBox(height: 24),
          const _AnnouncementsRibbon(),
          const SizedBox(height: 24),
        ],
      ),
    );
  }
}

class _Hero extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Text('مرحبًا يا طارق أحمد،',
                style: TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700)),
              const Spacer(),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: Colors.white.withValues(alpha: 0.18),
                  borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
                ),
                child: const Text(
                  'الصف الثاني عشر — علوم',
                  style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600),
                ),
              ),
            ],
          ),
          const SizedBox(height: 6),
          const Text('اليوم عندك ٤ حصص و٢ واجبات.',
            style: TextStyle(color: Colors.white70, fontSize: 14)),
          const SizedBox(height: 12),
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: Colors.white.withValues(alpha: 0.22),
                borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg),
              ),
              child: const Row(mainAxisSize: MainAxisSize.min, children: [
                Text('اذهب لجدول اليوم', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
                SizedBox(width: 6),
                Icon(Icons.arrow_forward_rounded, color: Colors.white, size: 16),
              ]),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatsRow extends StatelessWidget {
  const _StatsRow();
  @override
  Widget build(BuildContext context) {
    return Row(children: const [
      Expanded(child: _StatTile(value: '٩٤%', label: 'المعدل التراكمي')),
      SizedBox(width: 12),
      Expanded(child: _StatTile(value: '١٨/٢٠', label: 'واجبات مسلّمة')),
      SizedBox(width: 12),
      Expanded(child: _StatTile(value: '٩٨%', label: 'الحضور')),
    ]);
  }
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.value, required this.label});
  final String value; final String label;
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
        const SizedBox(height: 2),
        Text(label, style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
      ]),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;
  @override
  Widget build(BuildContext context) => Text(
    text,
    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface),
  );
}

class _TodayPeriodsScroller extends StatelessWidget {
  const _TodayPeriodsScroller();
  @override
  Widget build(BuildContext context) {
    final periods = const [
      _Period('الرياضيات', '08:00', 'د. أحمد', false),
      _Period('الفيزياء',  '09:00', 'د. ماجد', true),   // now
      _Period('الكيمياء',  '10:00', 'د. سارة', false),
      _Period('الأحياء',   '11:00', 'د. ليلى', false),
    ];
    return SizedBox(
      height: 120,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: periods.length,
        separatorBuilder: (_, __) => const SizedBox(width: 12),
        itemBuilder: (_, i) => _PeriodCard(periods[i]),
      ),
    );
  }
}

class _Period {
  final String subject; final String time; final String teacher; final bool live;
  const _Period(this.subject, this.time, this.teacher, this.live);
}

class _PeriodCard extends StatelessWidget {
  const _PeriodCard(this.p);
  final _Period p;
  @override
  Widget build(BuildContext context) {
    return Container(
      width: 160,
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        border: Border.all(color: ManasetyBrand.outline.withValues(alpha: 0.2)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Text(p.time, style: const TextStyle(fontFamily: 'monospace', fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
          const Spacer(),
          if (p.live) Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
            decoration: BoxDecoration(color: ManasetyBrand.success, borderRadius: BorderRadius.circular(999)),
            child: const Text('الآن', style: TextStyle(color: Colors.white, fontSize: 10, fontWeight: FontWeight.w700)),
          ),
        ]),
        const SizedBox(height: 8),
        Text(p.subject, style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        const SizedBox(height: 4),
        Text(p.teacher, style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
      ]),
    );
  }
}

class _UpcomingList extends StatelessWidget {
  const _UpcomingList();
  @override
  Widget build(BuildContext context) {
    return Column(children: const [
      _UpcomingItem('واجب الرياضيات — الفصل ٥', 'خلال ٣ ساعات', ManasetyBrand.warning),
      _UpcomingItem('اختبار قصير — الفيزياء',  'غدًا',        ManasetyBrand.blue),
      _UpcomingItem('تقرير مختبر — الكيمياء',   'الأسبوع القادم', ManasetyBrand.outline),
    ]);
  }
}

class _UpcomingItem extends StatelessWidget {
  const _UpcomingItem(this.title, this.due, this.tone);
  final String title; final String due; final Color tone;
  @override
  Widget build(BuildContext context) {
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        border: Border.all(color: ManasetyBrand.outline.withValues(alpha: 0.2)),
      ),
      child: Row(children: [
        Container(width: 4, height: 32, decoration: BoxDecoration(color: tone, borderRadius: BorderRadius.circular(2))),
        const SizedBox(width: 12),
        Expanded(child: Text(title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600, color: ManasetyBrand.onSurface))),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(color: tone.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(999)),
          child: Text(due, style: TextStyle(color: tone, fontSize: 11, fontWeight: FontWeight.w700)),
        ),
      ]),
    );
  }
}

class _AnnouncementsRibbon extends StatelessWidget {
  const _AnnouncementsRibbon();
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => Navigator.of(context).pushNamed(Routes.announcements),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLow,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        ),
        child: Row(children: [
          const Icon(Icons.campaign_rounded, color: ManasetyBrand.navy),
          const SizedBox(width: 12),
          const Expanded(child: Text('لديك إعلانان جديدان اليوم — اضغط للاطلاع', style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
          const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline),
        ]),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../pickup/pickup_banner.dart';
import '../data/home_repository.dart';

/// [STU] Home — data-driven. All content comes from `/student/home`.
/// Loading = skeleton, error = retryable card, empty = empty state.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(homeDataProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      body: Column(
        children: [
          const SafeArea(bottom: false, child: PickupBanner()),
          Expanded(
            child: RefreshIndicator(
              onRefresh: () async => ref.refresh(homeDataProvider.future),
              child: async.when(
                data: (data) => _HomeBody(data: data),
                loading: () => const _HomeSkeleton(),
                error: (e, _) => _HomeError(error: e,
                  onRetry: () => ref.invalidate(homeDataProvider)),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _HomeBody extends StatelessWidget {
  const _HomeBody({required this.data});
  final HomeData data;

  @override
  Widget build(BuildContext context) {
    final s = data.student;
    final stats = data.stats;
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _Hero(name: (s['full_name'] as String?) ?? '',
              classLabel: (s['class'] as String?) ?? '',
              todaysPeriodCount: data.todayPeriods.length,
              upcomingCount: data.upcoming.length),
        const SizedBox(height: 16),
        Row(children: [
          Expanded(child: _StatTile(
            value: stats.gpaPct == null ? '—' : '${stats.gpaPct!.toStringAsFixed(0)}%',
            label: 'المعدل التراكمي')),
          const SizedBox(width: 12),
          Expanded(child: _StatTile(
            value: '${stats.assignmentsSubmitted}/${stats.assignmentsTotal}',
            label: 'واجبات مسلّمة')),
          const SizedBox(width: 12),
          Expanded(child: _StatTile(
            value: stats.attendancePct == null ? '—' : '${stats.attendancePct!.toStringAsFixed(0)}%',
            label: 'الحضور')),
        ]),
        const SizedBox(height: 24),
        const _SectionTitle('جدول اليوم'),
        const SizedBox(height: 8),
        if (data.todayPeriods.isEmpty)
          const _EmptyBlock(label: 'لا حصص مسجّلة اليوم')
        else _TodayPeriodsScroller(periods: data.todayPeriods),
        const SizedBox(height: 24),
        const _SectionTitle('الاستحقاقات القريبة'),
        const SizedBox(height: 8),
        if (data.upcoming.isEmpty)
          const _EmptyBlock(label: 'لا استحقاقات قريبة')
        else _UpcomingList(items: data.upcoming),
        const SizedBox(height: 24),
        if (data.announcements.isNotEmpty)
          _AnnouncementsRibbon(count: data.announcements.length),
        const SizedBox(height: 24),
      ],
    );
  }
}

class _Hero extends StatelessWidget {
  const _Hero({required this.name, required this.classLabel,
    required this.todaysPeriodCount, required this.upcomingCount});
  final String name;
  final String classLabel;
  final int todaysPeriodCount;
  final int upcomingCount;
  @override
  Widget build(BuildContext context) {
    final greeting = 'مرحبًا يا ${name.isEmpty ? "طالب" : name}،';
    final line2 = 'اليوم عندك $todaysPeriodCount حصص و$upcomingCount استحقاقات.';
    return Container(
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: ManasetyBrand.primaryGradient,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(greeting,
            style: const TextStyle(color: Colors.white, fontSize: 20, fontWeight: FontWeight.w700))),
          if (classLabel.isNotEmpty) Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.18),
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusLg)),
            child: Text(classLabel,
              style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600)),
          ),
        ]),
        const SizedBox(height: 6),
        Text(line2, style: const TextStyle(color: Colors.white70, fontSize: 14)),
      ]),
    );
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
  Widget build(BuildContext context) => Text(text,
    style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface));
}

class _TodayPeriodsScroller extends StatelessWidget {
  const _TodayPeriodsScroller({required this.periods});
  final List<TodayPeriod> periods;
  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 120,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        itemCount: periods.length,
        separatorBuilder: (_, __) => const SizedBox(width: 12),
        itemBuilder: (_, i) {
          final p = periods[i];
          return Container(
            width: 160,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: ManasetyBrand.surfaceContainerLowest,
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
              border: Border.all(color: ManasetyBrand.outline.withValues(alpha: 0.2)),
            ),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(p.start ?? '', style: const TextStyle(fontFamily: 'monospace', fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
              const SizedBox(height: 8),
              Text(p.subject ?? '—', style: const TextStyle(fontSize: 15, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
              const SizedBox(height: 4),
              Text(p.teacher ?? '', style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
              const Spacer(),
              if (p.room != null) Text('قاعة ${p.room}',
                style: const TextStyle(fontSize: 11, color: ManasetyBrand.navy, fontWeight: FontWeight.w600)),
            ]),
          );
        },
      ),
    );
  }
}

class _UpcomingList extends StatelessWidget {
  const _UpcomingList({required this.items});
  final List<UpcomingItem> items;
  @override
  Widget build(BuildContext context) {
    return Column(children: [
      for (final it in items) Container(
        margin: const EdgeInsets.only(bottom: 8),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLowest,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
          border: Border.all(color: ManasetyBrand.outline.withValues(alpha: 0.2)),
        ),
        child: Row(children: [
          Icon(it.kind == 'quiz' ? Icons.quiz_rounded : Icons.assignment_rounded,
            color: ManasetyBrand.navy, size: 22),
          const SizedBox(width: 10),
          Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(it.title, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
            if (it.subject != null) Text(it.subject!,
              style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
          ])),
          if (it.dueAt != null) Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: ManasetyBrand.warning.withValues(alpha: 0.14),
              borderRadius: BorderRadius.circular(999),
            ),
            child: Text(_shortDate(it.dueAt!),
              style: const TextStyle(color: ManasetyBrand.warning, fontSize: 11, fontWeight: FontWeight.w700)),
          ),
        ]),
      ),
    ]);
  }

  String _shortDate(String iso) {
    try {
      final d = DateTime.parse(iso).toLocal();
      return '${d.year}-${d.month.toString().padLeft(2,'0')}-${d.day.toString().padLeft(2,'0')}';
    } catch (_) { return iso; }
  }
}

class _AnnouncementsRibbon extends StatelessWidget {
  const _AnnouncementsRibbon({required this.count});
  final int count;
  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => context.push(Routes.announcements),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLow,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        ),
        child: Row(children: [
          const Icon(Icons.campaign_rounded, color: ManasetyBrand.navy),
          const SizedBox(width: 12),
          Expanded(child: Text('لديك $count إعلانات جديدة — اضغط للاطلاع',
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600))),
          const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline),
        ]),
      ),
    );
  }
}

class _EmptyBlock extends StatelessWidget {
  const _EmptyBlock({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: const EdgeInsets.all(20),
    decoration: BoxDecoration(
      color: ManasetyBrand.surfaceContainerLow,
      borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
    ),
    child: Center(child: Text(label,
      style: const TextStyle(color: ManasetyBrand.onSurfaceVariant))),
  );
}

class _HomeSkeleton extends StatelessWidget {
  const _HomeSkeleton();
  @override
  Widget build(BuildContext context) {
    Widget bar([double w = double.infinity, double h = 16]) => Container(
      width: w, height: h,
      decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLow,
        borderRadius: BorderRadius.circular(6)),
    );
    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Container(height: 120, decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLow,
          borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl))),
        const SizedBox(height: 16),
        Row(children: [for (int i = 0; i < 3; i++)
          Expanded(child: Padding(padding: EdgeInsets.only(left: i < 2 ? 12 : 0),
            child: Container(height: 68, decoration: BoxDecoration(
              color: ManasetyBrand.surfaceContainerLow,
              borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl))))),
        ]),
        const SizedBox(height: 24),
        bar(120, 16),
        const SizedBox(height: 12),
        SizedBox(height: 120, child: ListView.separated(
          scrollDirection: Axis.horizontal, itemCount: 3,
          separatorBuilder: (_, __) => const SizedBox(width: 12),
          itemBuilder: (_, __) => Container(width: 160, decoration: BoxDecoration(
            color: ManasetyBrand.surfaceContainerLow,
            borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl))),
        )),
      ],
    );
  }
}

class _HomeError extends StatelessWidget {
  const _HomeError({required this.error, required this.onRetry});
  final Object error;
  final VoidCallback onRetry;
  @override
  Widget build(BuildContext context) {
    return ListView(children: [
      const SizedBox(height: 80),
      const Icon(Icons.wifi_off_rounded, size: 64, color: ManasetyBrand.outline),
      const SizedBox(height: 12),
      Center(child: Text(error is ApiException ? (error as ApiException).message : 'تعذّر تحميل البيانات',
        style: const TextStyle(color: ManasetyBrand.onSurfaceVariant))),
      const SizedBox(height: 16),
      Center(child: TextButton.icon(
        onPressed: onRetry, icon: const Icon(Icons.refresh_rounded),
        label: const Text('حاول مرة أخرى'))),
    ]);
  }
}

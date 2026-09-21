import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../data/home_repository.dart';

/// [TCH] Home — matches `design_refs/tch/home.png`.
///
/// Layout: profile bar → navy hero (greeting + start-first-period CTA) →
/// 3 stat tiles → current period navy card + upcoming rows → pending
/// grading list → parent messages list. All data from /api/teacher/home.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(homeDataProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(homeDataProvider.future),
        child: async.when(
          data: (d) => _Body(data: d),
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => _Err(err: e, onRetry: () => ref.invalidate(homeDataProvider)),
        ),
      ),
    );
  }
}

class _Body extends StatelessWidget {
  const _Body({required this.data});
  final TeacherHomeData data;

  @override
  Widget build(BuildContext context) {
    final t = data.teacher;
    final name = (t['full_name'] as String?) ?? 'المعلم';
    final spec = (t['specialization'] as String?) ?? (t['subject'] as String?) ?? '';
    final avatar = (t['avatar_url'] as String?) ?? '';

    final periods = [...data.todayPeriods]
      ..sort((a, b) => a.periodOrder.compareTo(b.periodOrder));
    final current = periods.isNotEmpty ? periods.first : null;
    final upcoming = periods.length > 1 ? periods.sublist(1) : <TodayPeriod>[];

    return ListView(padding: const EdgeInsets.fromLTRB(16, 16, 16, 24), children: [
      _ProfileBar(name: name, spec: spec, avatarUrl: avatar),
      const SizedBox(height: 16),
      _HeroCard(name: name,
        todayCount: data.stats.todayPeriodCount,
        pendingCount: data.stats.pendingGrading,
        firstPeriodSubject: current?.subject),
      const SizedBox(height: 16),
      Row(children: [
        Expanded(child: _StatTile(
          value: '${data.stats.studentCount}',
          label: 'طالبًا مسجلًا',
          color: const Color(0xFF10B981),
          bg: const Color(0xFFECFDF5),
          icon: Icons.groups_rounded)),
        const SizedBox(width: 10),
        Expanded(child: _StatTile(
          value: '${data.stats.pendingGrading}',
          label: 'في التصحيح',
          color: const Color(0xFFF59E0B),
          bg: const Color(0xFFFEF3C7),
          icon: Icons.edit_note_rounded)),
        const SizedBox(width: 10),
        Expanded(child: _StatTile(
          value: '${data.stats.todayPeriodCount}',
          label: 'حصص اليوم',
          color: const Color(0xFF2563EB),
          bg: const Color(0xFFDBEAFE),
          icon: Icons.calendar_today_rounded)),
      ]),
      const SizedBox(height: 20),
      _SectionHeader(
        title: 'جدول اليوم',
        trailingText: 'عرض الأسبوع ›',
        onTap: () => context.push(Routes.timetable)),
      const SizedBox(height: 10),
      if (current == null)
        const _EmptyRow(label: 'لا حصص مسجّلة اليوم')
      else _CurrentPeriodCard(period: current, onAttendance: () =>
        context.push(Routes.attendance)),
      const SizedBox(height: 10),
      for (int i = 0; i < upcoming.length; i++) ...[
        _UpcomingPeriodRow(period: upcoming[i]),
        const SizedBox(height: 8),
      ],
      const SizedBox(height: 12),
      _SectionHeader(
        title: 'في انتظار التصحيح',
        leadingIcon: Icons.task_alt_rounded,
        trailingText: '${data.pendingGrading.length} تكليف'),
      const SizedBox(height: 10),
      if (data.pendingGrading.isEmpty)
        const _EmptyRow(label: 'لا شيء بانتظار التصحيح')
      else for (final p in data.pendingGrading) ...[
        _PendingRow(item: p),
        const SizedBox(height: 8),
      ],
      const SizedBox(height: 12),
      _SectionHeader(
        title: 'رسائل أولياء الأمور',
        leadingIcon: Icons.mark_email_unread_rounded,
        trailingText: 'عرض الكل ›',
        onTap: () => context.push(Routes.messages)),
      const SizedBox(height: 10),
      if (data.recentMessages.isEmpty)
        const _EmptyRow(label: 'لا رسائل جديدة')
      else for (final m in data.recentMessages) ...[
        _MessageRow(msg: m),
        const SizedBox(height: 8),
      ],
    ]);
  }
}

class _ProfileBar extends StatelessWidget {
  const _ProfileBar({required this.name, required this.spec, required this.avatarUrl});
  final String name, spec, avatarUrl;
  @override
  Widget build(BuildContext context) => Row(children: [
    Stack(clipBehavior: Clip.none, children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: Colors.white,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: const Color(0xFFE2E8F0))),
        child: const Icon(Icons.notifications_none_rounded, size: 20, color: ManasetyBrand.onSurface)),
      Positioned(right: 6, top: 6, child: Container(width: 8, height: 8,
        decoration: const BoxDecoration(color: ManasetyBrand.error, shape: BoxShape.circle))),
    ]),
    const Spacer(),
    Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
      Text(name, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      if (spec.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2),
        child: Text(spec, style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant))),
    ]),
    const SizedBox(width: 10),
    Stack(children: [
      Container(width: 44, height: 44,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 2),
          image: avatarUrl.isNotEmpty
            ? DecorationImage(image: NetworkImage(avatarUrl), fit: BoxFit.cover) : null,
          gradient: avatarUrl.isEmpty ? ManasetyBrand.primaryGradient : null,
        ),
        child: avatarUrl.isEmpty
          ? Center(child: Text(name.isNotEmpty ? name.characters.first : 'م',
              style: const TextStyle(color: Colors.white, fontSize: 16, fontWeight: FontWeight.w800)))
          : null),
      Positioned(bottom: 0, right: 0, child: Container(width: 12, height: 12,
        decoration: BoxDecoration(color: const Color(0xFF10B981),
          shape: BoxShape.circle,
          border: Border.all(color: Colors.white, width: 2)))),
    ]),
  ]);
}

class _HeroCard extends StatelessWidget {
  const _HeroCard({required this.name, required this.todayCount,
    required this.pendingCount, required this.firstPeriodSubject});
  final String name; final int todayCount, pendingCount;
  final String? firstPeriodSubject;

  String _hijriDate() {
    // Simple Arabic date — the API doesn't return calendar strings yet.
    const months = ['يناير','فبراير','مارس','أبريل','مايو','يونيو',
      'يوليو','أغسطس','سبتمبر','أكتوبر','نوفمبر','ديسمبر'];
    const days = ['الاثنين','الثلاثاء','الأربعاء','الخميس','الجمعة','السبت','الأحد'];
    final now = DateTime.now();
    return '${days[now.weekday - 1]}، ${now.day} ${months[now.month - 1]}';
  }

  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(18),
    decoration: BoxDecoration(
      gradient: ManasetyBrand.primaryGradient,
      borderRadius: BorderRadius.circular(20),
      boxShadow: ManasetyBrand.shadowRaised,
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(color: const Color(0xFF10B981),
            borderRadius: BorderRadius.circular(999)),
          child: const Text('يوم نشط',
            style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700))),
        const Spacer(),
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(color: Colors.white.withValues(alpha: 0.15),
            borderRadius: BorderRadius.circular(999)),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.wb_sunny_rounded, color: Colors.white, size: 12),
            const SizedBox(width: 6),
            Text(_hijriDate(),
              style: const TextStyle(color: Colors.white, fontSize: 11)),
          ])),
      ]),
      const SizedBox(height: 18),
      Row(children: [
        Expanded(child: Text('صباح الخير، $name 👋',
          style: const TextStyle(color: Colors.white, fontSize: 20,
            fontWeight: FontWeight.w800, height: 1.3))),
      ]),
      const SizedBox(height: 8),
      Text('لديك اليوم $todayCount حصص مجدولة و$pendingCount واجبًا بانتظار اعتماد التصحيح.',
        style: const TextStyle(color: Colors.white70, fontSize: 12, height: 1.6)),
      const SizedBox(height: 16),
      Material(color: Colors.white,
        borderRadius: BorderRadius.circular(999),
        child: InkWell(borderRadius: BorderRadius.circular(999), onTap: () {},
          child: Container(width: double.infinity, height: 48,
            alignment: Alignment.center,
            child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              const Icon(Icons.play_arrow_rounded, color: ManasetyBrand.navy),
              const SizedBox(width: 6),
              Text(firstPeriodSubject != null
                ? 'بدء الحصة الأولى ($firstPeriodSubject)'
                : 'بدء الحصة الأولى',
                style: const TextStyle(color: ManasetyBrand.navy,
                  fontSize: 14, fontWeight: FontWeight.w800)),
            ])))),
    ]),
  );
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.value, required this.label,
    required this.color, required this.bg, required this.icon});
  final String value, label;
  final Color color, bg;
  final IconData icon;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(width: 36, height: 36,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)),
        child: Icon(icon, color: color, size: 20)),
      const SizedBox(height: 10),
      Text(value, style: const TextStyle(fontSize: 22,
        fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
    ]),
  );
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, this.trailingText,
    this.onTap, this.leadingIcon});
  final String title; final String? trailingText;
  final VoidCallback? onTap; final IconData? leadingIcon;
  @override
  Widget build(BuildContext context) => Row(children: [
    if (leadingIcon != null) ...[
      Icon(leadingIcon, size: 16, color: ManasetyBrand.navy),
      const SizedBox(width: 6),
    ],
    Text(title, style: const TextStyle(fontSize: 15,
      fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
    const Spacer(),
    if (trailingText != null) InkWell(onTap: onTap,
      child: Text(trailingText!, style: const TextStyle(
        color: Color(0xFF2563EB), fontSize: 12, fontWeight: FontWeight.w700))),
  ]);
}

class _CurrentPeriodCard extends StatelessWidget {
  const _CurrentPeriodCard({required this.period, required this.onAttendance});
  final TodayPeriod period; final VoidCallback onAttendance;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(16),
    decoration: BoxDecoration(
      gradient: ManasetyBrand.primaryGradient,
      borderRadius: BorderRadius.circular(18),
      boxShadow: ManasetyBrand.shadowRaised,
    ),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Row(children: [
        Container(padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
          decoration: BoxDecoration(color: const Color(0xFFEF4444),
            borderRadius: BorderRadius.circular(999)),
          child: const Row(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.circle, size: 8, color: Colors.white),
            SizedBox(width: 6),
            Text('جارية الآن',
              style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700)),
          ])),
        const Spacer(),
        Row(mainAxisSize: MainAxisSize.min, children: [
          const Icon(Icons.access_time_rounded, size: 14, color: Colors.white70),
          const SizedBox(width: 4),
          Text('${period.start ?? "--:--"}-${period.end ?? "--:--"}',
            style: const TextStyle(color: Colors.white, fontSize: 12,
              fontWeight: FontWeight.w700, fontFamily: 'monospace')),
        ]),
      ]),
      const SizedBox(height: 12),
      Text(period.subject ?? 'الحصة الحالية',
        style: const TextStyle(color: Colors.white, fontSize: 18,
          fontWeight: FontWeight.w800)),
      const SizedBox(height: 4),
      Text([
        if (period.section != null) period.section!,
        if (period.room != null) 'قاعة ${period.room}',
      ].join(' · '),
        style: const TextStyle(color: Colors.white70, fontSize: 12)),
      const SizedBox(height: 14),
      Row(children: [
        const Icon(Icons.access_time_rounded, size: 14, color: Colors.white70),
        const SizedBox(width: 6),
        Text(period.periodName ?? 'الحصة الحالية',
          style: const TextStyle(color: Colors.white, fontSize: 12)),
        const Spacer(),
        Material(color: Colors.white,
          borderRadius: BorderRadius.circular(999),
          child: InkWell(borderRadius: BorderRadius.circular(999), onTap: onAttendance,
            child: Container(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
              child: const Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.how_to_reg_rounded, size: 16, color: ManasetyBrand.navy),
                SizedBox(width: 6),
                Text('رصد الحضور',
                  style: TextStyle(color: ManasetyBrand.navy,
                    fontSize: 12, fontWeight: FontWeight.w800)),
              ])))),
      ]),
    ]),
  );
}

class _UpcomingPeriodRow extends StatelessWidget {
  const _UpcomingPeriodRow({required this.period});
  final TodayPeriod period;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('الحصة', style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
        Text('${period.periodOrder}', style: const TextStyle(fontSize: 20,
          fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      ]),
      const SizedBox(width: 14),
      Container(width: 1, height: 40, color: const Color(0xFFE2E8F0)),
      const SizedBox(width: 14),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(period.subject ?? 'حصة',
          style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        const SizedBox(height: 3),
        Text([
          if (period.section != null) period.section!,
          if (period.room != null) 'قاعة ${period.room}',
        ].join(' · '),
          style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
      ])),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(
          period.start != null && period.end != null
            ? '${period.start}-${period.end}'
            : (period.start ?? ''),
          style: const TextStyle(
            fontFamily: 'monospace', fontSize: 12,
            fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
        const SizedBox(height: 2),
        Text(period.periodName ?? 'حصة',
          style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
    ]),
  );
}

class _PendingRow extends StatelessWidget {
  const _PendingRow({required this.item});
  final PendingGradingItem item;
  @override
  Widget build(BuildContext context) {
    final palette = _subjectPalette(item.subject);
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: Row(children: [
        Container(width: 40, height: 40,
          decoration: BoxDecoration(color: palette.$2,
            borderRadius: BorderRadius.circular(10)),
          child: Icon(palette.$3, color: palette.$1, size: 22)),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(item.title, style: const TextStyle(
            fontSize: 13, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
          const SizedBox(height: 2),
          Text('${item.subject ?? ""} · ${item.ungradedCount} تسليمات جديدة',
            style: const TextStyle(fontSize: 11, color: Color(0xFF2563EB))),
        ])),
        Container(padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
          decoration: BoxDecoration(color: const Color(0xFF2563EB),
            borderRadius: BorderRadius.circular(999)),
          child: const Text('صحّح الآن',
            style: TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w700))),
      ]),
    );
  }
}

(Color, Color, IconData) _subjectPalette(String? subject) {
  final s = (subject ?? '').toLowerCase();
  if (s.contains('رياض') || s.contains('math')) {
    return (const Color(0xFF1E3A8A), const Color(0xFFDBEAFE), Icons.calculate_rounded);
  }
  if (s.contains('فيزياء') || s.contains('physics')) {
    return (const Color(0xFFF59E0B), const Color(0xFFFEF3C7), Icons.bolt_rounded);
  }
  if (s.contains('علوم') || s.contains('كيمياء') || s.contains('science')) {
    return (const Color(0xFF0EA5E9), const Color(0xFFE0F2FE), Icons.science_rounded);
  }
  if (s.contains('عرب') || s.contains('لغ')) {
    return (const Color(0xFF7C3AED), const Color(0xFFEDE9FE), Icons.menu_book_rounded);
  }
  return (const Color(0xFF2563EB), const Color(0xFFDBEAFE), Icons.assignment_rounded);
}

class _MessageRow extends StatelessWidget {
  const _MessageRow({required this.msg});
  final RecentMessage msg;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: const Color(0xFFF1F5F9),
          shape: BoxShape.circle),
        child: Center(child: Text(
          msg.from.isNotEmpty ? msg.from.characters.first : 'م',
          style: const TextStyle(fontWeight: FontWeight.w800, color: ManasetyBrand.navy)))),
      const SizedBox(width: 12),
      Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Expanded(child: Text(msg.from,
            style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface),
            maxLines: 1, overflow: TextOverflow.ellipsis)),
          if ((msg.createdAt ?? '').isNotEmpty) Text(_relTime(msg.createdAt!),
            style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
        ]),
        const SizedBox(height: 2),
        Text(msg.subject,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface),
          maxLines: 1, overflow: TextOverflow.ellipsis),
        if (msg.preview.isNotEmpty) Padding(padding: const EdgeInsets.only(top: 2),
          child: Text(msg.preview,
            style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant),
            maxLines: 2, overflow: TextOverflow.ellipsis)),
      ])),
    ]),
  );
}

String _relTime(String iso) {
  final t = DateTime.tryParse(iso);
  if (t == null) return '';
  final d = DateTime.now().difference(t);
  if (d.inMinutes < 60) return 'منذ ${d.inMinutes} دقيقة';
  if (d.inHours < 24) return 'منذ ${d.inHours} ساعات';
  return 'منذ ${d.inDays} يوم';
}

class _EmptyRow extends StatelessWidget {
  const _EmptyRow({required this.label});
  final String label;
  @override
  Widget build(BuildContext context) => Container(width: double.infinity,
    padding: const EdgeInsets.symmetric(vertical: 24, horizontal: 16),
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

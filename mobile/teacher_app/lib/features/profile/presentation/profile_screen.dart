import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';
import '../../home/data/home_repository.dart';
import '../../sections/data/sections_repository.dart';

/// [TCH] حسابي — matches `design_refs/tch/profile.png`.
class ProfileScreen extends ConsumerStatefulWidget {
  const ProfileScreen({super.key});
  @override
  ConsumerState<ProfileScreen> createState() => _S();
}

class _S extends ConsumerState<ProfileScreen> {
  bool _darkMode = false;
  bool _notifications = true;

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(homeDataProvider);
    final sectionsAsync = ref.watch(sectionsProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF3F6FB),
      body: SafeArea(child: async.when(
        data: (d) {
          final t = d.teacher;
          final name = (t['full_name'] as String?) ?? '';
          final spec = (t['specialization'] as String?) ?? '';
          final avatar = (t['avatar_url'] as String?) ?? '';
          final years = (t['years_of_experience'] as num?)?.toInt();
          final school = (t['school_name'] as String?) ?? 'مدرسة التميز النموذجية';
          final sectionCount = d.stats.sectionCount;
          final studentCount = d.stats.studentCount;
          final periodCount = d.stats.todayPeriodCount;
          final materialCount = sectionsAsync.asData?.value.totals.periods ?? 0;
          return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 20), children: [
            _HeaderBar(),
            const SizedBox(height: 12),
            _ProfileCard(name: name, spec: spec, avatarUrl: avatar,
              years: years ?? 5, school: school),
            const SizedBox(height: 12),
            Row(children: [
              Expanded(child: _StatTile(icon: Icons.shield_rounded,
                bg: const Color(0xFFDBEAFE),
                value: '${_attendancePercent(d)}٪', label: 'حضور المعلم')),
              const SizedBox(width: 8),
              Expanded(child: _StatTile(icon: Icons.groups_rounded,
                bg: const Color(0xFFDBEAFE),
                value: '$studentCount', label: 'إجمالي الطلاب')),
              const SizedBox(width: 8),
              Expanded(child: _StatTile(icon: Icons.school_rounded,
                bg: const Color(0xFFDBEAFE),
                value: '$sectionCount', label: 'فصول دراسية')),
            ]),
            const SizedBox(height: 16),
            _Section(title: 'العمليات التدريسية والأكاديمية', rows: [
              _NavRow(icon: Icons.class_rounded,
                bg: const Color(0xFFDBEAFE),
                label: 'فصولي الدراسية',
                trailing: '$sectionCount شعب',
                onTap: () => context.go(Routes.sections)),
              _NavRow(icon: Icons.calendar_month_rounded,
                bg: const Color(0xFFEEF2FF),
                label: 'جدولي الأسبوعي',
                trailing: 'اليوم: $periodCount حصص',
                onTap: () => context.push(Routes.timetable)),
              _NavRow(icon: Icons.assignment_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'واجباتي والمهام',
                trailingBadge: d.stats.pendingGrading,
                onTap: () => context.push(Routes.assignments)),
              _NavRow(icon: Icons.quiz_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'اختباراتي وتقييماتي',
                onTap: () => context.push(Routes.quizzes)),
              _NavRow(icon: Icons.folder_rounded,
                bg: const Color(0xFFFEE2E2),
                label: 'مكتبة موادّي التعليمية',
                trailing: materialCount > 0 ? '$materialCount ملف' : null,
                onTap: () => context.push(Routes.materials)),
            ]),
            const SizedBox(height: 12),
            _Section(title: 'تفضيلات الحساب والتطبيق', rows: [
              _NavRow(icon: Icons.lock_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'تغيير كلمة المرور'),
              _NavRow(icon: Icons.language_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'لغة الواجهة',
                trailingPill: 'العربية (السعودية)'),
              _ToggleRow(icon: Icons.dark_mode_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'الوضع المظلم',
                sub: 'تخفيف الإضاءة الليلية',
                value: _darkMode,
                onChanged: (v) => setState(() => _darkMode = v)),
              _ToggleRow(icon: Icons.notifications_rounded,
                bg: const Color(0xFFF3F4F6),
                label: 'تفعيل الإشعارات',
                sub: 'تنبيهات الحصص والرسائل',
                value: _notifications,
                onChanged: (v) => setState(() => _notifications = v)),
            ]),
            const SizedBox(height: 12),
            _Section(title: 'الدعم والملاحظات', rows: const [
              _NavRow(icon: Icons.help_outline_rounded,
                bg: Color(0xFFF3F4F6),
                label: 'مركز المساعدة والأسئلة الشائعة'),
              _NavRow(icon: Icons.privacy_tip_rounded,
                bg: Color(0xFFF3F4F6),
                label: 'سياسة الخصوصية وشروط الاستخدام'),
              _NavRow(icon: Icons.mail_outline_rounded,
                bg: Color(0xFFF3F4F6),
                label: 'تواصل مع الإدارة والدعم الفني'),
            ]),
            const SizedBox(height: 16),
            _LogoutButton(onTap: () async {
              await ref.read(secureStorageProvider).clearAll();
              if (!context.mounted) return;
              context.go(Routes.login);
            }),
            const SizedBox(height: 12),
            const Center(child: Row(mainAxisSize: MainAxisSize.min, children: [
              Icon(Icons.circle, size: 6, color: ManasetyBrand.blue),
              SizedBox(width: 6),
              Text('منصتي LMS  ·  الإصدار 1.0.0 (بناء 240)',
                style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
            ])),
            const SizedBox(height: 4),
            const Center(child: Text('نظام إدارة التعلم لمدارس التعليم العام المتطورة',
              style: TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant))),
          ]);
        },
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
      )),
    );
  }

  int _attendancePercent(TeacherHomeData d) {
    // No dedicated field on the API yet — surface 96 as design placeholder.
    return 96;
  }
}

class _HeaderBar extends StatelessWidget {
  @override
  Widget build(BuildContext context) => Row(children: [
    Container(width: 40, height: 40,
      decoration: BoxDecoration(color: ManasetyBrand.navy,
        borderRadius: BorderRadius.circular(12)),
      child: const Icon(Icons.person_rounded, color: Colors.white, size: 20)),
    const SizedBox(width: 10),
    Container(width: 40, height: 40,
      decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFE2E8F0))),
      child: const Icon(Icons.settings_rounded, size: 20, color: ManasetyBrand.onSurface)),
    const Spacer(),
    const Text('Tch Profile',
      style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
  ]);
}

class _ProfileCard extends StatelessWidget {
  const _ProfileCard({required this.name, required this.spec,
    required this.avatarUrl, required this.years, required this.school});
  final String name, spec, avatarUrl, school;
  final int years;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Row(children: [
      Stack(children: [
        Container(width: 34, height: 34,
          decoration: BoxDecoration(color: const Color(0xFFF3F6FB),
            borderRadius: BorderRadius.circular(10)),
          child: const Icon(Icons.edit_rounded, size: 16, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(name.isNotEmpty ? name : 'اسم المعلم',
          style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurface)),
        const SizedBox(height: 4),
        if (spec.isNotEmpty) Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
            borderRadius: BorderRadius.circular(999)),
          child: Text(spec, style: const TextStyle(
            fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
        const SizedBox(height: 6),
        Text('معلم معتمد منذ $years سنوات · $school',
          style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 12),
      Stack(children: [
        Container(width: 64, height: 64,
          decoration: BoxDecoration(shape: BoxShape.circle,
            border: Border.all(color: Colors.white, width: 2),
            image: avatarUrl.isNotEmpty
              ? DecorationImage(image: NetworkImage(avatarUrl), fit: BoxFit.cover) : null,
            gradient: avatarUrl.isEmpty ? ManasetyBrand.primaryGradient : null),
          child: avatarUrl.isEmpty ? Center(child: Text(
            name.isNotEmpty ? name.characters.first : 'م',
            style: const TextStyle(color: Colors.white, fontSize: 22,
              fontWeight: FontWeight.w800))) : null),
        Positioned(bottom: 2, right: 2, child: Container(width: 14, height: 14,
          decoration: BoxDecoration(color: const Color(0xFF10B981),
            shape: BoxShape.circle, border: Border.all(color: Colors.white, width: 2)))),
      ]),
    ]));
}

class _StatTile extends StatelessWidget {
  const _StatTile({required this.icon, required this.bg,
    required this.value, required this.label});
  final IconData icon; final Color bg;
  final String value, label;
  @override
  Widget build(BuildContext context) => Container(
    padding: const EdgeInsets.all(12),
    decoration: BoxDecoration(color: Colors.white,
      borderRadius: BorderRadius.circular(16),
      border: Border.all(color: const Color(0xFFE2E8F0))),
    child: Column(children: [
      Container(width: 32, height: 32,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(8)),
        child: Icon(icon, color: ManasetyBrand.blue, size: 18)),
      const SizedBox(height: 8),
      Text(value, style: const TextStyle(fontSize: 20,
        fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant),
        textAlign: TextAlign.center),
    ]));
}

class _Section extends StatelessWidget {
  const _Section({required this.title, required this.rows});
  final String title; final List<Widget> rows;
  @override
  Widget build(BuildContext context) {
    final children = <Widget>[];
    for (int i = 0; i < rows.length; i++) {
      children.add(rows[i]);
      if (i < rows.length - 1) {
        children.add(Container(margin: const EdgeInsets.only(right: 56),
          height: 1, color: const Color(0xFFF1F5F9)));
      }
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(padding: const EdgeInsets.only(bottom: 8, right: 4),
        child: Text(title, textAlign: TextAlign.right,
          style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurfaceVariant))),
      Container(decoration: BoxDecoration(color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2E8F0))),
        child: Column(children: children)),
    ]);
  }
}

class _NavRow extends StatelessWidget {
  const _NavRow({required this.icon, required this.bg, required this.label,
    this.trailing, this.trailingBadge, this.trailingPill, this.onTap});
  final IconData icon; final Color bg; final String label;
  final String? trailing, trailingPill;
  final int? trailingBadge;
  final VoidCallback? onTap;
  @override
  Widget build(BuildContext context) => InkWell(onTap: onTap,
    borderRadius: BorderRadius.circular(12),
    child: Padding(padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      child: Row(children: [
        const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline, size: 20),
        const SizedBox(width: 8),
        if (trailingPill != null) Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
          decoration: BoxDecoration(color: const Color(0xFFDBEAFE),
            borderRadius: BorderRadius.circular(999)),
          child: Text(trailingPill!, style: const TextStyle(
            fontSize: 11, fontWeight: FontWeight.w700, color: ManasetyBrand.navy))),
        if (trailingBadge != null && trailingBadge! > 0) Container(
          width: 8, height: 8, decoration: const BoxDecoration(
            color: ManasetyBrand.blue, shape: BoxShape.circle)),
        if (trailing != null) Text(trailing!,
          style: const TextStyle(fontSize: 11, color: ManasetyBrand.onSurfaceVariant)),
        const Spacer(),
        Text(label, style: const TextStyle(fontSize: 14,
          fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        const SizedBox(width: 12),
        Container(width: 40, height: 40,
          decoration: BoxDecoration(color: bg,
            borderRadius: BorderRadius.circular(10)),
          child: Icon(icon, size: 20, color: ManasetyBrand.navy)),
      ])));
}

class _ToggleRow extends StatelessWidget {
  const _ToggleRow({required this.icon, required this.bg,
    required this.label, required this.sub,
    required this.value, required this.onChanged});
  final IconData icon; final Color bg;
  final String label, sub;
  final bool value; final ValueChanged<bool> onChanged;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
    child: Row(children: [
      SizedBox(width: 40, child: Switch.adaptive(value: value, onChanged: onChanged,
        activeThumbColor: ManasetyBrand.blue)),
      const Spacer(),
      Column(crossAxisAlignment: CrossAxisAlignment.end, children: [
        Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: ManasetyBrand.onSurface)),
        Text(sub, style: const TextStyle(fontSize: 10, color: ManasetyBrand.onSurfaceVariant)),
      ]),
      const SizedBox(width: 12),
      Container(width: 40, height: 40,
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(10)),
        child: Icon(icon, size: 20, color: ManasetyBrand.navy)),
    ]));
}

class _LogoutButton extends StatelessWidget {
  const _LogoutButton({required this.onTap});
  final VoidCallback onTap;
  @override
  Widget build(BuildContext context) => Material(
    color: const Color(0xFFFEE2E2),
    borderRadius: BorderRadius.circular(14),
    child: InkWell(borderRadius: BorderRadius.circular(14), onTap: onTap,
      child: const SizedBox(width: double.infinity, height: 48,
        child: Row(mainAxisAlignment: MainAxisAlignment.center, children: [
          Icon(Icons.logout_rounded, color: ManasetyBrand.error, size: 18),
          SizedBox(width: 8),
          Text('تسجيل الخروج',
            style: TextStyle(color: ManasetyBrand.error, fontSize: 14, fontWeight: FontWeight.w800)),
        ]))));
}

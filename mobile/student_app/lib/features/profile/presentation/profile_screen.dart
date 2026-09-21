import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';
import '../data/profile_repository.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(profileProvider);
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('حسابي')),
      body: RefreshIndicator(
        onRefresh: () async => ref.refresh(profileProvider.future),
        child: async.when(
          data: (p) => ListView(padding: const EdgeInsets.all(16), children: [
            _Header(p: p),
            const SizedBox(height: 16),
            if (p.gpaPct != null || p.attendancePct != null) Row(children: [
              if (p.gpaPct != null) Expanded(child: _stat(
                '${p.gpaPct!.toStringAsFixed(0)}%', 'المعدل التراكمي')),
              if (p.gpaPct != null && p.attendancePct != null) const SizedBox(width: 12),
              if (p.attendancePct != null) Expanded(child: _stat(
                '${p.attendancePct!.toStringAsFixed(0)}%', 'الحضور')),
            ]),
            const SizedBox(height: 16),
            _Section('الأكاديميّة', [
              _Row(icon: Icons.grading_rounded, label: 'تقاريري',
                onTap: () => context.push(Routes.grades)),
              _Row(icon: Icons.calendar_month_rounded, label: 'جدولي',
                onTap: () => context.go(Routes.timetable)),
              _Row(icon: Icons.fact_check_rounded, label: 'حضوري',
                onTap: () => context.push(Routes.attendance)),
            ]),
            const SizedBox(height: 16),
            _Section('الإعدادات', [
              const _Row(icon: Icons.lock_rounded, label: 'تغيير كلمة المرور'),
              const _Row(icon: Icons.language_rounded, label: 'لغة الواجهة — العربية'),
              _Row(icon: Icons.dark_mode_rounded, label: 'الوضع المظلم',
                trailing: Switch(value: false, onChanged: (_) {})),
              _Row(icon: Icons.notifications_rounded, label: 'تفعيل الإشعارات',
                trailing: Switch(value: true, onChanged: (_) {})),
            ]),
            const SizedBox(height: 16),
            _Section('الدعم', [
              const _Row(icon: Icons.help_outline_rounded, label: 'مركز المساعدة'),
              const _Row(icon: Icons.privacy_tip_rounded,   label: 'سياسة الخصوصية'),
              const _Row(icon: Icons.mail_outline_rounded,  label: 'تواصل مع الإدارة'),
            ]),
            const SizedBox(height: 16),
            Container(
              decoration: BoxDecoration(color: ManasetyBrand.error.withValues(alpha: 0.08),
                borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
              child: ListTile(
                leading: const Icon(Icons.logout_rounded, color: ManasetyBrand.error),
                title: const Text('تسجيل الخروج',
                  style: TextStyle(color: ManasetyBrand.error, fontWeight: FontWeight.w700)),
                onTap: () async {
                  await ref.read(secureStorageProvider).clearAll();
                  if (!context.mounted) return;
                  context.go(Routes.login);
                },
              ),
            ),
            const SizedBox(height: 8),
            const Center(child: Text('الإصدار 0.1.0 · منصتي',
              style: TextStyle(color: ManasetyBrand.outline, fontSize: 12))),
          ]),
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(child: Text(e is ApiException ? e.message : 'تعذّر التحميل')),
        ),
      ),
    );
  }

  Widget _stat(String value, String label) => Container(
    padding: const EdgeInsets.all(14),
    decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLowest,
      borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
      boxShadow: ManasetyBrand.shadowDefault),
    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(value, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800, color: ManasetyBrand.navy)),
      const SizedBox(height: 2),
      Text(label, style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant)),
    ]),
  );
}

class _Header extends StatelessWidget {
  const _Header({required this.p});
  final ProfileData p;
  @override
  Widget build(BuildContext context) {
    final initial = (p.fullName ?? 'ط').characters.take(1).toString();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault),
      child: Row(children: [
        Container(width: 72, height: 72,
          decoration: const BoxDecoration(
            gradient: ManasetyBrand.primaryGradient, shape: BoxShape.circle),
          child: Center(child: Text(initial,
            style: const TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w800))),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(p.fullName ?? '—', style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          const SizedBox(height: 4),
          if (p.permanentCode != null) Text(p.permanentCode!,
            style: const TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant, fontFamily: 'monospace')),
          if (p.classLabel != null) Padding(padding: const EdgeInsets.only(top: 4),
            child: Text(p.classLabel!, style: const TextStyle(fontSize: 12,
              color: ManasetyBrand.navy, fontWeight: FontWeight.w600))),
        ])),
      ]),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title, this.rows);
  final String title; final List<Widget> rows;
  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Padding(padding: const EdgeInsets.only(bottom: 8, right: 4),
        child: Text(title, style: const TextStyle(fontSize: 13,
          fontWeight: FontWeight.w800, color: ManasetyBrand.onSurfaceVariant))),
      Container(decoration: BoxDecoration(color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl)),
        child: Column(children: rows)),
    ],
  );
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.label, this.onTap, this.trailing});
  final IconData icon; final String label; final VoidCallback? onTap; final Widget? trailing;
  @override
  Widget build(BuildContext context) => ListTile(
    leading: Icon(icon, color: ManasetyBrand.navy),
    title: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
    trailing: trailing ?? const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline),
    onTap: onTap,
  );
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/router/routes.dart';
import '../../../core/storage/secure_storage.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      backgroundColor: ManasetyBrand.surface,
      appBar: AppBar(title: const Text('حسابي')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          _Header(),
          const SizedBox(height: 16),
          _Section('الأكاديميّة', [
            _Row(icon: Icons.grading_rounded,     label: 'تقاريري', onTap: () => context.push(Routes.grades)),
            _Row(icon: Icons.calendar_month_rounded, label: 'جدولي', onTap: () => context.go(Routes.timetable)),
            _Row(icon: Icons.fact_check_rounded,  label: 'حضوري',  onTap: () => context.push(Routes.attendance)),
          ]),
          const SizedBox(height: 16),
          _Section('الإعدادات', [
            _Row(icon: Icons.lock_rounded,        label: 'تغيير كلمة المرور'),
            _Row(icon: Icons.language_rounded,    label: 'لغة الواجهة — العربية'),
            _Row(icon: Icons.dark_mode_rounded,   label: 'الوضع المظلم', trailing: Switch(value: false, onChanged: (_) {})),
            _Row(icon: Icons.notifications_rounded, label: 'تفعيل الإشعارات', trailing: Switch(value: true, onChanged: (_) {})),
          ]),
          const SizedBox(height: 16),
          _Section('الدعم', [
            _Row(icon: Icons.help_outline_rounded,   label: 'مركز المساعدة'),
            _Row(icon: Icons.privacy_tip_rounded,     label: 'سياسة الخصوصية'),
            _Row(icon: Icons.mail_outline_rounded,    label: 'تواصل مع الإدارة'),
          ]),
          const SizedBox(height: 16),
          Container(
            decoration: BoxDecoration(
              color: ManasetyBrand.error.withValues(alpha: 0.08),
              borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
            ),
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
        ],
      ),
    );
  }
}

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: ManasetyBrand.surfaceContainerLowest,
        borderRadius: BorderRadius.circular(ManasetyBrand.radius2xl),
        boxShadow: ManasetyBrand.shadowDefault,
      ),
      child: Row(children: [
        Container(
          width: 72, height: 72,
          decoration: BoxDecoration(
            gradient: ManasetyBrand.primaryGradient,
            shape: BoxShape.circle,
          ),
          child: const Center(
            child: Text('ط', style: TextStyle(color: Colors.white, fontSize: 32, fontWeight: FontWeight.w800)),
          ),
        ),
        const SizedBox(width: 12),
        Expanded(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: const [
          Text('طارق أحمد', style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800)),
          SizedBox(height: 4),
          Text('STU-2024-01047', style: TextStyle(fontSize: 12, color: ManasetyBrand.onSurfaceVariant, fontFamily: 'monospace')),
          SizedBox(height: 4),
          Text('الصف الثاني عشر — علوم', style: TextStyle(fontSize: 12, color: ManasetyBrand.navy, fontWeight: FontWeight.w600)),
        ])),
      ]),
    );
  }
}

class _Section extends StatelessWidget {
  const _Section(this.title, this.rows);
  final String title; final List<Widget> rows;
  @override
  Widget build(BuildContext context) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Padding(padding: const EdgeInsets.only(bottom: 8, right: 4),
        child: Text(title, style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: ManasetyBrand.onSurfaceVariant))),
      Container(
        decoration: BoxDecoration(
          color: ManasetyBrand.surfaceContainerLowest,
          borderRadius: BorderRadius.circular(ManasetyBrand.radiusXl),
        ),
        child: Column(children: rows),
      ),
    ]);
  }
}

class _Row extends StatelessWidget {
  const _Row({required this.icon, required this.label, this.onTap, this.trailing});
  final IconData icon; final String label; final VoidCallback? onTap; final Widget? trailing;
  @override
  Widget build(BuildContext context) {
    return ListTile(
      leading: Icon(icon, color: ManasetyBrand.navy),
      title: Text(label, style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600)),
      trailing: trailing ?? const Icon(Icons.chevron_left_rounded, color: ManasetyBrand.outline),
      onTap: onTap,
    );
  }
}

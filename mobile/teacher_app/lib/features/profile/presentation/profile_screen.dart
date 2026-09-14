import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../core/env.dart';
import 'package:manasety_ui/manasety_ui.dart';
import '../../auth/application/auth_controller.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final user = auth is Authenticated ? auth.user : null;

    return SingleChildScrollView(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Center(
            child: ManasetyLogo(
              variant: ManasetyLogoVariant.emblem,
              size: 100,
            ),
          ),
          const SizedBox(height: 8),
          Center(
            child: Text(
              Env.institutionNameAr,
              textAlign: TextAlign.center,
              style: TextStyle(
                color: Theme.of(context).colorScheme.primary,
                fontWeight: FontWeight.w800,
                fontSize: 14,
              ),
            ),
          ),
          const SizedBox(height: 24),
          Card(
            child: Column(
              children: [
                _row(context, Icons.person_outline, 'الاسم الكامل',
                    user?.fullName ?? '—'),
                const Divider(height: 1),
                _row(context, Icons.badge_outlined, 'اسم المستخدم',
                    user?.username ?? '—'),
                const Divider(height: 1),
                _row(context, Icons.work_outline, 'الدور', user?.roleAr ?? '—'),
                const Divider(height: 1),
                _row(context, Icons.school_outlined, 'المؤسسة',
                    Env.institutionNameAr),
              ],
            ),
          ),
          const SizedBox(height: 16),
          Card(
            child: Column(
              children: [
                ListTile(
                  leading: Icon(Icons.upload_file, color: Theme.of(context).colorScheme.primary),
                  title: const Text('رفع مادة جديدة',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text('PDF أو صورة أو رابط لطلاب فصلك',
                      style: TextStyle(color: context.tokens.muted, fontSize: 12)),
                  trailing: Icon(Icons.chevron_left, color: context.tokens.muted),
                  onTap: () => context.push('/materials/upload'),
                ),
                const Divider(height: 1),
                ListTile(
                  leading: Icon(Icons.lock_outline, color: Theme.of(context).colorScheme.primary),
                  title: const Text('تغيير كلمة المرور',
                      style: TextStyle(fontWeight: FontWeight.w700)),
                  trailing: Icon(Icons.chevron_left, color: context.tokens.muted),
                  onTap: () => context.push('/profile/change-password'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 24),
          OutlinedButton.icon(
            onPressed: () =>
                ref.read(authControllerProvider.notifier).signOut(),
            icon: const Icon(Icons.logout),
            label: const Text('تسجيل الخروج'),
            style: OutlinedButton.styleFrom(
              foregroundColor: AppColors.danger,
              side: const BorderSide(color: AppColors.danger),
              padding: const EdgeInsets.symmetric(vertical: 14),
            ),
          ),
          const SizedBox(height: 24),
          // Day 13 — pulled version from `package_info_plus` at runtime so
          // it can't drift from pubspec.yaml (was hard-coded 0.2.0 while
          // pubspec was 0.3.0).
          Center(
            child: FutureBuilder<PackageInfo>(
              future: PackageInfo.fromPlatform(),
              builder: (context, snap) {
                final v = snap.data?.version ?? '…';
                return Text(
                  'بوابة المعلم • الإصدار $v',
                  style: TextStyle(color: context.tokens.muted, fontSize: 11),
                );
              },
            ),
          ),
        ],
      ),
    );
  }

  Widget _row(BuildContext context, IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      child: Row(
        children: [
          Icon(icon, color: Theme.of(context).colorScheme.primary, size: 20),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    color: context.tokens.muted,
                    fontSize: 11,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  value,
                  style: TextStyle(
                    color: context.tokens.ink,
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

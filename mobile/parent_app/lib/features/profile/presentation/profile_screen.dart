import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:package_info_plus/package_info_plus.dart';

import '../../../core/env.dart';
import 'package:manasety_ui/manasety_ui.dart';
import '../../auth/application/auth_controller.dart';
import '../../children/data/children_repository.dart';

class ProfileScreen extends ConsumerWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final user = auth is Authenticated ? auth.user : null;
    final children = ref.watch(childrenProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('الحساب'),
        actions: [
          // Sprint 11 — pencil opens self-service edit-profile screen
          IconButton(
            tooltip: 'تعديل الحساب',
            icon: const Icon(Icons.edit_outlined),
            onPressed: () => context.push('/profile/edit'),
          ),
        ],
      ),
      body: SingleChildScrollView(
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
                ],
              ),
            ),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
              child: Text(
                'أبناؤك',
                style: TextStyle(
                  color: Theme.of(context).colorScheme.primary,
                  fontWeight: FontWeight.w800,
                ),
              ),
            ),
            Card(
              child: AsyncValueWidget(
                value: children,
                data: (list) {
                  if (list.isEmpty) {
                    return const ListTile(
                      title: Text('لا يوجد أبناء مسجّلون'),
                    );
                  }
                  return Column(
                    children: list
                        .map(
                          (c) => Column(
                            children: [
                              ListTile(
                                leading: Icon(Icons.person,
                                    color: Theme.of(context).colorScheme.primary),
                                title: Text(
                                  c.fullName,
                                  style: const TextStyle(
                                      fontWeight: FontWeight.w700),
                                ),
                                subtitle: Text(
                                  '${c.permanentCode} • ${c.currentSection ?? '—'}',
                                ),
                              ),
                              if (c != list.last) const Divider(height: 1),
                            ],
                          ),
                        )
                        .toList(),
                  );
                },
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
            // Day 13 — pulled version from `package_info_plus` at runtime
            // so it can't drift from pubspec.yaml (was hard-coded 0.2.0
            // while pubspec was 0.3.0).
            Center(
              child: FutureBuilder<PackageInfo>(
                future: PackageInfo.fromPlatform(),
                builder: (context, snap) {
                  final v = snap.data?.version ?? '…';
                  return Text(
                    'بوابة ولي الأمر • الإصدار $v',
                    style: TextStyle(color: context.tokens.muted, fontSize: 11),
                  );
                },
              ),
            ),
          ],
        ),
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
                Text(label,
                    style:
                        TextStyle(color: context.tokens.muted, fontSize: 11)),
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

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../../../core/env.dart';
import '../../../shared/models/child_brief.dart';
import '../../auth/application/auth_controller.dart';
import '../data/children_repository.dart';

const _lastChildKey = 'last_picked_child_id';

/// Parent hub — SIMPLIFIED after the sliver/IntrinsicHeight rendering bug.
///
/// Structure: navy AppBar → single scrollable `ListView` containing a small
/// gradient hero, a plain stat strip, a subheading, and a list of straight
/// bordered Cards. No slivers, no IntrinsicHeight, no AccentRailCard —
/// bulletproof layout that renders on the first frame in every mode.
class ChildrenScreen extends ConsumerWidget {
  const ChildrenScreen({super.key});

  Future<void> _rememberPick(int id) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_lastChildKey, id);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);
    final user = auth is Authenticated ? auth.user : null;
    final children = ref.watch(childrenProvider);

    return Scaffold(
      appBar: AppBar(
        title: const Text('أبناؤك'),
        actions: [
          // Always expose the profile entry point — a parent with zero linked
          // children would otherwise have no way to reach the account screen
          // (that button normally lives in child_detail_screen's AppBar).
          IconButton(
            tooltip: 'الحساب',
            icon: const Icon(Icons.person_outline),
            onPressed: () => context.push('/profile'),
          ),
        ],
      ),
      body: AppRefreshIndicator(
        onRefresh: () async {
          ref.invalidate(childrenProvider);
          await ref.read(childrenProvider.future);
        },
        child: AsyncValueWidget<List<ChildBrief>>(
          value: children,
          onRetry: () => ref.invalidate(childrenProvider),
          data: (list) {
            if (list.isEmpty) {
              return const RefreshableEmpty(
                child: EmptyState(
                  icon: Icons.family_restroom,
                  illustration: EmptyIllustration(kind: ManasetyEmpty.family),
                  title: 'لا يوجد أبناء مسجّلون',
                  description: 'تواصل مع إدارة المؤسسة للمساعدة.',
                ),
              );
            }
            // Auto-navigate when only one child.
            if (list.length == 1) {
              WidgetsBinding.instance.addPostFrameCallback((_) {
                _rememberPick(list.first.id);
                if (context.mounted) {
                  context.go('/children/${list.first.id}');
                }
              });
              return const Center(child: CircularProgressIndicator());
            }

            return ListView(
              physics: const AlwaysScrollableScrollPhysics(),
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
              children: [
                _HeroCard(
                  greeting: 'أهلاً، ${user?.fullName ?? ''}',
                  subtitle: Env.institutionNameAr,
                ),
                const SizedBox(height: 16),
                _StatStrip(childCount: list.length),
                const SizedBox(height: 20),
                const _SubHeading(text: 'اختر ابنك'),
                const SizedBox(height: 8),
                for (final c in list) ...[
                  _ChildCard(
                    child: c,
                    onTap: () async {
                      await _rememberPick(c.id);
                      if (context.mounted) {
                        context.push('/children/${c.id}');
                      }
                    },
                  ),
                  const SizedBox(height: 10),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _HeroCard extends StatelessWidget {
  final String greeting;
  final String subtitle;
  const _HeroCard({required this.greeting, required this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topRight,
          end: Alignment.bottomLeft,
          colors: [AppColors.navy, AppColors.navySoft],
        ),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            greeting,
            style: const TextStyle(
              color: Colors.white,
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: TextStyle(
              color: Colors.white.withValues(alpha: 0.85),
              fontSize: 12,
            ),
          ),
          const SizedBox(height: 10),
          Container(
            width: 40,
            height: 3,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ],
      ),
    );
  }
}

class _StatStrip extends StatelessWidget {
  final int childCount;
  const _StatStrip({required this.childCount});

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _tile(context, arabize(childCount), 'الأبناء', Icons.family_restroom)),
        const SizedBox(width: 8),
        Expanded(child: _tile(context, arabize(childCount), 'مسجّلين', Icons.school_outlined)),
      ],
    );
  }

  Widget _tile(BuildContext context, String value, String label, IconData icon) {
    final t = context.tokens;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 14),
      decoration: BoxDecoration(
        color: t.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: t.border),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(icon, size: 16, color: AppColors.navy),
              const SizedBox(width: 6),
              Text(
                value,
                style: const TextStyle(
                  color: AppColors.navy,
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            label,
            style: TextStyle(
              color: t.muted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

class _SubHeading extends StatelessWidget {
  final String text;
  const _SubHeading({required this.text});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 6),
      child: Row(
        children: [
          Container(
            width: 4,
            height: 18,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
          const SizedBox(width: 8),
          Text(
            text,
            style: const TextStyle(
              color: AppColors.navy,
              fontWeight: FontWeight.w800,
              fontSize: 15,
            ),
          ),
        ],
      ),
    );
  }
}

class _ChildCard extends StatelessWidget {
  final ChildBrief child;
  final VoidCallback onTap;
  const _ChildCard({required this.child, required this.onTap});

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    // Day 12 — Fold name + section + code into one SR summary; without this
    // TalkBack reads each Text child as a separate node and never announces
    // "button", so the card doesn't sound tappable.
    final subtitle = [
      if (child.currentSection != null) child.currentSection!,
      if (child.currentYear != null) child.currentYear!,
    ].join(' — ');
    return Semantics(
      button: true,
      label: [
        child.fullName,
        if (subtitle.isNotEmpty) subtitle,
        'الرقم: ${child.permanentCode}',
      ].join(' — '),
      excludeSemantics: true,
      child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: t.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: t.border),
        ),
        child: Row(
          children: [
            Container(
              width: 4,
              height: 48,
              decoration: BoxDecoration(
                color: AppColors.gold,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 12),
            // Day 10 — Hero flight into child_detail_screen's AppBar avatar.
            Hero(
              tag: 'child-avatar-${child.id}',
              child: Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: AppColors.sky.withValues(alpha: 0.4),
                  shape: BoxShape.circle,
                ),
                alignment: Alignment.center,
                child: const Icon(Icons.person, color: AppColors.navy, size: 22),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    child.fullName,
                    style: TextStyle(
                      color: t.ink,
                      fontWeight: FontWeight.w800,
                      fontSize: 15,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    [
                      if (child.currentSection != null) child.currentSection!,
                      if (child.currentYear != null) child.currentYear!,
                    ].join(' • '),
                    style: TextStyle(color: t.muted, fontSize: 12),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    'الرقم: ${child.permanentCode}',
                    style: TextStyle(color: t.muted, fontSize: 11),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_left, color: t.muted),
          ],
        ),
      ),
    ),
    );
  }
}

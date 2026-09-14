import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../core/env.dart';
import '../../../shared/models/section_brief.dart';
import '../../auth/application/auth_controller.dart';
import '../../schedule/data/schedule_repository.dart';
import '../data/sections_repository.dart';

/// Teacher hub — SIMPLIFIED after the sliver/IntrinsicHeight rendering bug.
/// Same shape as parent ChildrenScreen: hero + stat strip + subheading + list.
class SectionsScreen extends ConsumerWidget {
  const SectionsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);
    final user = authState is Authenticated ? authState.user : null;
    final sections = ref.watch(sectionsProvider);
    final schedule = ref.watch(teacherScheduleProvider);

    final todayDayId = _todayDayId();
    final todaysSectionIds = <int>{};
    var todaysSlotCount = 0;
    schedule.whenData((slots) {
      for (final s in slots) {
        if (s.dayId == todayDayId) {
          todaysSlotCount++;
          if (s.sectionId != null) todaysSectionIds.add(s.sectionId!);
        }
      }
    });

    return AppRefreshIndicator(
      onRefresh: () async {
        ref.invalidate(sectionsProvider);
        ref.invalidate(teacherScheduleProvider);
        await ref.read(sectionsProvider.future);
      },
      child: AsyncValueWidget<List<SectionBrief>>(
        value: sections,
        onRetry: () => ref.invalidate(sectionsProvider),
        data: (list) {
          final distinctSubjects = <String>{
            for (final s in list) ...s.subjects.map((x) => x.name),
          };

          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 24),
            children: [
              _HeroCard(
                greeting: 'مرحبًا، ${user?.fullName ?? ''}',
                subtitle: Env.institutionNameAr,
              ),
              const SizedBox(height: 16),
              _StatStrip(
                sections: list.length,
                subjects: distinctSubjects.length,
                todayClasses: todaysSlotCount,
              ),
              const SizedBox(height: 20),
              if (list.isEmpty)
                const EmptyState(
                  icon: Icons.school_outlined,
                  illustration: EmptyIllustration(kind: ManasetyEmpty.classroom),
                  title: 'لم تُسند إليك فصول بعد',
                  description: 'تواصل مع إدارة المؤسسة لإسناد فصل دراسي.',
                )
              else ...[
                const _SubHeading(text: 'فصولك'),
                const SizedBox(height: 8),
                for (final section in list) ...[
                  _SectionCard(
                    section: section,
                    hasToday: todaysSectionIds.contains(section.id),
                    onTap: () => context.push('/sections/${section.id}'),
                  ),
                  const SizedBox(height: 10),
                ],
              ],
            ],
          );
        },
      ),
    );
  }

  int _todayDayId() {
    final wd = DateTime.now().weekday;
    const map = {
      DateTime.sunday: 1,
      DateTime.monday: 2,
      DateTime.tuesday: 3,
      DateTime.wednesday: 4,
      DateTime.thursday: 5,
      DateTime.friday: 6,
      DateTime.saturday: 7,
    };
    return map[wd] ?? 1;
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
  final int sections;
  final int subjects;
  final int todayClasses;
  const _StatStrip({
    required this.sections,
    required this.subjects,
    required this.todayClasses,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(child: _tile(context, arabize(sections), 'الفصول', Icons.class_outlined, AppColors.navy)),
        const SizedBox(width: 8),
        Expanded(child: _tile(context, arabize(subjects), 'المواد', Icons.menu_book_outlined, AppColors.navy)),
        const SizedBox(width: 8),
        Expanded(child: _tile(context, arabize(todayClasses), 'حصص اليوم', Icons.today_outlined, AppColors.goldInk)),
      ],
    );
  }

  Widget _tile(BuildContext context, String value, String label, IconData icon, Color accent) {
    final t = context.tokens;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 14),
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
              Icon(icon, size: 16, color: accent),
              const SizedBox(width: 6),
              Flexible(
                child: Text(
                  value,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: accent,
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 2),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
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

class _SectionCard extends StatelessWidget {
  final SectionBrief section;
  final bool hasToday;
  final VoidCallback onTap;
  const _SectionCard({
    required this.section,
    required this.hasToday,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    // Day 12 — Merge card visuals into one SR summary + button role.
    final subjectsSummary = section.subjects.isEmpty
        ? ''
        : ' — ${arabize(section.subjects.length)} مواد';
    return Semantics(
      button: true,
      label: '${section.name}$subjectsSummary${hasToday ? '، اليوم' : ''}',
      excludeSemantics: true,
      child: InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(12),
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: t.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: hasToday ? AppColors.gold : t.border,
            width: hasToday ? 1.4 : 1,
          ),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Container(
                  width: 4,
                  height: 40,
                  decoration: BoxDecoration(
                    color: hasToday ? AppColors.gold : AppColors.navy,
                    borderRadius: BorderRadius.circular(2),
                  ),
                ),
                const SizedBox(width: 12),
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: AppColors.sky.withValues(alpha: 0.4),
                    shape: BoxShape.circle,
                  ),
                  alignment: Alignment.center,
                  child: const Icon(Icons.class_outlined, color: AppColors.navy, size: 22),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    section.name,
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      color: t.ink,
                      fontSize: 15,
                    ),
                  ),
                ),
                if (hasToday)
                  Container(
                    padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                    decoration: BoxDecoration(
                      color: AppColors.gold.withValues(alpha: 0.18),
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: const Text(
                      'اليوم',
                      style: TextStyle(
                        color: AppColors.goldDark,
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  )
                else
                  Icon(Icons.chevron_left, color: t.muted),
              ],
            ),
            if (section.subjects.isNotEmpty) ...[
              const SizedBox(height: 10),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: section.subjects.map((s) {
                  // Day 6 — each chip in its subject-hashed color so scanning
                  // the section-list mirrors the timetable's color story.
                  // Day 12 hot-fix — original chip painted `c` on `c@14%`, so
                  // on medium-saturation palette entries the text nearly
                  // vanished. Text now blends toward ink for legibility while
                  // the accent tint still carries the subject identity.
                  final c = subjectAccent(s.name);
                  final darkText = Color.lerp(AppColors.ink, c, 0.35)!;
                  return Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                    decoration: BoxDecoration(
                      color: c.withValues(alpha: 0.18),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: c.withValues(alpha: 0.55)),
                    ),
                    child: Text(
                      s.name,
                      style: TextStyle(
                        color: darkText,
                        fontSize: 11,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  );
                }).toList(),
              ),
            ],
          ],
        ),
      ),
    ),
    );
  }
}

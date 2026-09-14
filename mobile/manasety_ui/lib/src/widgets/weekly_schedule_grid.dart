import 'package:flutter/material.dart';

import '../models/schedule_slot.dart';
import '../theme/arabize.dart';
import '../theme/colors.dart';
import '../theme/subject_palette.dart';
import '../theme/tokens.dart';
import 'empty_illustration.dart';
import 'empty_state.dart';
import 'refreshable_empty.dart';

/// شبكة جدول أسبوعية — تُستخدم في تطبيقي المعلم وولي الأمر.
///
/// Day 6: each slot row is color-coded by its subject (via `subjectAccent`)
/// with a leading rail + tinted time chip + subject icon inline. The day-card
/// matching today's weekday gets a gold outline + "اليوم" pill.
class WeeklyScheduleGrid extends StatelessWidget {
  final List<ScheduleSlot> slots;
  final bool showTeacher;

  const WeeklyScheduleGrid({
    super.key,
    required this.slots,
    this.showTeacher = true,
  });

  /// Map ISO weekday (Mon=1..Sun=7) to school day-id (Sun=1..Sat=7).
  static int _todayDayId() {
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

  @override
  Widget build(BuildContext context) {
    if (slots.isEmpty) {
      // Day 13 — upgraded the bare Padding+Center+Text to a proper
      // illustrated EmptyState wrapped in RefreshableEmpty so the schedule
      // tabs' outer RefreshIndicator can still fire on an empty grid.
      return const RefreshableEmpty(
        child: EmptyState(
          icon: Icons.calendar_month_outlined,
          illustration: EmptyIllustration(kind: ManasetyEmpty.calendar),
          title: 'لا توجد حصص مجدولة',
          description: 'سيظهر الجدول هنا فور اعتماد إدارة المؤسسة له.',
        ),
      );
    }
    final byDay = <int, List<ScheduleSlot>>{};
    for (final s in slots) {
      byDay.putIfAbsent(s.dayId, () => []).add(s);
    }
    final dayIds = byDay.keys.toList()..sort();
    final todayId = _todayDayId();

    return ListView.separated(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      itemCount: dayIds.length,
      separatorBuilder: (_, __) => const SizedBox(height: 14),
      itemBuilder: (_, idx) {
        final dayId = dayIds[idx];
        final daySlots = byDay[dayId]!
          ..sort((a, b) => a.periodId.compareTo(b.periodId));
        return _DayCard(
          slots: daySlots,
          showTeacher: showTeacher,
          isToday: dayId == todayId,
        );
      },
    );
  }
}

class _DayCard extends StatelessWidget {
  final List<ScheduleSlot> slots;
  final bool showTeacher;
  final bool isToday;
  const _DayCard({
    required this.slots,
    required this.showTeacher,
    required this.isToday,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    // Day 10 — animated border so the today-highlight tweens in.
    return AnimatedContainer(
      duration: const Duration(milliseconds: 300),
      curve: Curves.easeOutCubic,
      decoration: BoxDecoration(
        color: t.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: isToday ? AppColors.gold : t.border,
          width: isToday ? 2 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                Container(
                  width: 6,
                  height: 18,
                  decoration: BoxDecoration(
                    color: AppColors.gold,
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    slots.first.dayName,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.primary,
                      fontWeight: FontWeight.w800,
                      fontSize: 15,
                    ),
                  ),
                ),
                if (isToday)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 8,
                      vertical: 2,
                    ),
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
                  ),
              ],
            ),
            Divider(height: 18, color: t.border),
            ...slots.map((s) => _SlotRow(slot: s, showTeacher: showTeacher)),
          ],
        ),
      ),
    );
  }
}

class _SlotRow extends StatelessWidget {
  final ScheduleSlot slot;
  final bool showTeacher;
  const _SlotRow({required this.slot, required this.showTeacher});

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final accent = subjectAccent(slot.subjectName);
    final icon = subjectIcon(slot.subjectName);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Leading rail in subject color.
            Container(
              width: 3,
              decoration: BoxDecoration(
                color: accent,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 10),
            // Time chip in subject color tint.
            // Day 12 hot-fix — text was `accent` on `accent@18%`; lerp toward
            // ink so light-hue subjects (steel-blue, olive) stay legible.
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: accent.withValues(alpha: 0.22),
                borderRadius: BorderRadius.circular(6),
              ),
              child: Text(
                arabize('${slot.startTime} - ${slot.endTime}'),
                style: TextStyle(
                  color: Color.lerp(AppColors.ink, accent, 0.35),
                  fontWeight: FontWeight.w800,
                  fontSize: 11,
                  fontFeatures: const [FontFeature.tabularFigures()],
                ),
              ),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  Row(
                    children: [
                      Icon(icon, size: 14, color: accent),
                      const SizedBox(width: 6),
                      Flexible(
                        child: Text(
                          slot.subjectName,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            color: t.ink,
                            fontSize: 14,
                          ),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 2),
                  Text(
                    [
                      slot.periodName,
                      if (slot.sectionName != null) slot.sectionName!,
                      if (showTeacher && slot.teacherName != null) slot.teacherName!,
                    ].join(' • '),
                    style: TextStyle(color: t.muted, fontSize: 12),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:intl/intl.dart';
import 'package:manasety_ui/manasety_ui.dart';

import '../../../shared/models/attendance.dart';
import '../data/attendance_repository.dart';

/// Attendance tab — Day 5 shape: hero donut → stat strip → month grid →
/// recent-records list. Turns raw attendance records into a glanceable
/// dashboard the parent can read without scanning individual dates.
class ChildAttendanceTab extends ConsumerWidget {
  final int childId;
  const ChildAttendanceTab({super.key, required this.childId});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final att = ref.watch(childAttendanceProvider(childId));
    return RefreshIndicator(
      onRefresh: () async {
        ref.invalidate(childAttendanceProvider(childId));
        await ref.read(childAttendanceProvider(childId).future);
      },
      child: AsyncValueWidget<ChildAttendance>(
        value: att,
        onRetry: () => ref.invalidate(childAttendanceProvider(childId)),
        data: (data) {
          if (data.records.isEmpty) {
            return const RefreshableEmpty(
              child: EmptyState(
                icon: Icons.event_available,
                illustration: EmptyIllustration(kind: ManasetyEmpty.calendar),
                title: 'لا توجد سجلات حضور بعد',
              ),
            );
          }
          final s = data.summary;
          final cells = data.records
              .map((r) => AttendanceCell(
                    date: r.date,
                    status: _statusStr(r.status),
                  ))
              .toList();
          final recent = [...data.records]
            ..sort((a, b) => b.date.compareTo(a.date));

          return ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 20, 16, 24),
            children: [
              // Hero: donut + tally strip.
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: context.tokens.surface,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: context.tokens.border),
                ),
                child: Column(
                  children: [
                    AttendanceDonut(
                      present: s.present,
                      absent: s.absent,
                      late: s.late,
                      total: s.total,
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        Expanded(child: _tally(context, arabize(s.present), 'حاضر', AppColors.success)),
                        Expanded(child: _tally(context, arabize(s.absent), 'غائب', AppColors.danger)),
                        Expanded(child: _tally(context, arabize(s.late), 'متأخّر', AppColors.goldInk)),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),
              // Month grid.
              const _SubHeading(text: 'سجلّ الشهر'),
              const SizedBox(height: 8),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: context.tokens.surface,
                  borderRadius: BorderRadius.circular(14),
                  border: Border.all(color: context.tokens.border),
                ),
                child: AttendanceMonthGrid(records: cells),
              ),
              const SizedBox(height: 20),
              // Recent records — cap at 10.
              const _SubHeading(text: 'آخر التسجيلات'),
              const SizedBox(height: 8),
              for (final r in recent.take(10)) _RecentRow(record: r),
            ],
          );
        },
      ),
    );
  }

  String _statusStr(AttendanceStatus s) {
    switch (s) {
      case AttendanceStatus.present:
        return 'present';
      case AttendanceStatus.absent:
        return 'absent';
      case AttendanceStatus.late:
        return 'late';
      case AttendanceStatus.unknown:
        return 'unknown';
    }
  }

  Widget _tally(BuildContext context, String value, String label, Color color) {
    return Column(
      children: [
        Text(
          value,
          style: TextStyle(
            color: color,
            fontWeight: FontWeight.w900,
            fontSize: 18,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          label,
          style: TextStyle(
            color: context.tokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class _SubHeading extends StatelessWidget {
  final String text;
  const _SubHeading({required this.text});
  @override
  Widget build(BuildContext context) {
    return Row(
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
    );
  }
}

class _RecentRow extends StatelessWidget {
  final AttendanceRecord record;
  const _RecentRow({required this.record});

  StatusKind get _kind {
    switch (record.status) {
      case AttendanceStatus.present:
        return StatusKind.success;
      case AttendanceStatus.absent:
        return StatusKind.danger;
      case AttendanceStatus.late:
        return StatusKind.warn;
      case AttendanceStatus.unknown:
        return StatusKind.neutral;
    }
  }

  @override
  Widget build(BuildContext context) {
    final df = DateFormat.yMMMMd('ar');
    final t = context.tokens;
    return Container(
      margin: const EdgeInsets.only(bottom: 8),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: t.surface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: t.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              arabize(df.format(record.date)),
              style: TextStyle(
                color: t.ink,
                fontWeight: FontWeight.w700,
                fontSize: 13,
              ),
            ),
          ),
          StatusChip(label: record.status.labelAr, kind: _kind),
        ],
      ),
    );
  }
}

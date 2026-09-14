import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../theme/arabize.dart';
import '../theme/colors.dart';
import '../theme/tokens.dart';

/// Attendance record shape consumed by [AttendanceMonthGrid].
///
/// Kept as a bare tuple so `manasety_ui` doesn't depend on the app-specific
/// model class. Callers convert their own record type via [.map] before
/// passing the list in.
class AttendanceCell {
  final DateTime date;

  /// One of `'present'`, `'absent'`, `'late'`. Any other value = no record
  /// (renders as an inert grey cell).
  final String status;

  const AttendanceCell({required this.date, required this.status});
}

/// Calendar-grid view of one month's attendance. Each date renders as a
/// small rounded square colored by status (green / red / gold), with today
/// outlined in gold. Prev/next chevrons let the user page months.
///
/// Weeks start on Sunday (standard for Arabic-Islamic school calendars).
class AttendanceMonthGrid extends StatefulWidget {
  /// All records — the widget slices by the currently visible month.
  final List<AttendanceCell> records;

  /// Optional starting month. Defaults to the first day of the current month.
  final DateTime? initialMonth;

  /// Fired when the user taps a day cell that has a matching record.
  final ValueChanged<AttendanceCell>? onTapDay;

  const AttendanceMonthGrid({
    super.key,
    required this.records,
    this.initialMonth,
    this.onTapDay,
  });

  @override
  State<AttendanceMonthGrid> createState() => _AttendanceMonthGridState();
}

class _AttendanceMonthGridState extends State<AttendanceMonthGrid> {
  late DateTime _visibleMonth;

  @override
  void initState() {
    super.initState();
    final now = widget.initialMonth ?? DateTime.now();
    _visibleMonth = DateTime(now.year, now.month);
  }

  DateTime _addMonths(DateTime d, int n) =>
      DateTime(d.year, d.month + n, 1);

  void _prev() =>
      setState(() => _visibleMonth = _addMonths(_visibleMonth, -1));

  void _next() =>
      setState(() => _visibleMonth = _addMonths(_visibleMonth, 1));

  Color _cellColor(String status) {
    switch (status) {
      case 'present':
        return AppColors.success.withValues(alpha: 0.62);
      case 'absent':
        return AppColors.danger.withValues(alpha: 0.62);
      case 'late':
        return AppColors.gold.withValues(alpha: 0.7);
      default:
        return const Color(0x00000000);
    }
  }

  /// Day 12 — Arabic label for TalkBack; parallel channel to the color-coded
  /// `_cellColor` so color-blind and screen-reader users get the same info.
  String _statusAr(String? status) {
    switch (status) {
      case 'present':
        return 'حاضر';
      case 'absent':
        return 'غائب';
      case 'late':
        return 'متأخّر';
      default:
        return 'لا يوجد سجل';
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final monthLabel = DateFormat.yMMMM('ar').format(_visibleMonth);

    // Bucket records by day-of-month for the visible month.
    final byDay = <int, AttendanceCell>{};
    for (final r in widget.records) {
      if (r.date.year == _visibleMonth.year &&
          r.date.month == _visibleMonth.month) {
        byDay[r.date.day] = r;
      }
    }

    final firstOfMonth = _visibleMonth;
    final daysInMonth =
        DateTime(_visibleMonth.year, _visibleMonth.month + 1, 0).day;
    // Weekday(): Mon=1..Sun=7. We want Sun=0..Sat=6 so Sunday is the leading
    // column of the grid (RTL: rightmost).
    final leadingBlanks = firstOfMonth.weekday % 7; // Sun=0, Mon=1, ..., Sat=6

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);

    // Build cells: leading blanks + 1..daysInMonth.
    final cells = <Widget>[];
    for (var i = 0; i < leadingBlanks; i++) {
      cells.add(const SizedBox.shrink());
    }
    for (var d = 1; d <= daysInMonth; d++) {
      final date = DateTime(_visibleMonth.year, _visibleMonth.month, d);
      final rec = byDay[d];
      final isToday = date == today;
      cells.add(_DayCell(
        day: d,
        color: rec == null ? t.subtleBg : _cellColor(rec.status),
        isToday: isToday,
        statusAr: _statusAr(rec?.status),
        monthLabel: monthLabel,
        onTap: rec != null && widget.onTapDay != null
            ? () => widget.onTapDay!(rec)
            : null,
      ));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        // Month navigation header.
        Row(
          children: [
            IconButton(
              icon: const Icon(Icons.chevron_right),
              onPressed: _prev,
              tooltip: 'الشهر السابق',
            ),
            Expanded(
              child: Center(
                child: Text(
                  arabize(monthLabel),
                  style: TextStyle(
                    color: t.ink,
                    fontWeight: FontWeight.w800,
                    fontSize: 15,
                  ),
                ),
              ),
            ),
            IconButton(
              icon: const Icon(Icons.chevron_left),
              onPressed: _next,
              tooltip: 'الشهر التالي',
            ),
          ],
        ),
        const SizedBox(height: 6),
        // Weekday header row.
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceEvenly,
          children: const [
            _WeekdayLabel('الأحد'),
            _WeekdayLabel('الاثنين'),
            _WeekdayLabel('الثلاثاء'),
            _WeekdayLabel('الأربعاء'),
            _WeekdayLabel('الخميس'),
            _WeekdayLabel('الجمعة'),
            _WeekdayLabel('السبت'),
          ],
        ),
        const SizedBox(height: 6),
        // Day grid — 7 columns.
        GridView.count(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          crossAxisCount: 7,
          mainAxisSpacing: 4,
          crossAxisSpacing: 4,
          childAspectRatio: 1,
          children: cells,
        ),
        const SizedBox(height: 12),
        // Legend.
        Wrap(
          spacing: 12,
          runSpacing: 6,
          alignment: WrapAlignment.center,
          children: [
            _LegendDot(color: AppColors.success.withValues(alpha: 0.62), label: 'حاضر'),
            _LegendDot(color: AppColors.danger.withValues(alpha: 0.62), label: 'غائب'),
            _LegendDot(color: AppColors.gold.withValues(alpha: 0.7), label: 'متأخّر'),
            _LegendDot(color: t.subtleBg, label: 'بدون'),
          ],
        ),
      ],
    );
  }
}

class _DayCell extends StatelessWidget {
  final int day;
  final Color color;
  final bool isToday;
  final String statusAr;
  final String monthLabel;
  final VoidCallback? onTap;

  const _DayCell({
    required this.day,
    required this.color,
    required this.isToday,
    required this.statusAr,
    required this.monthLabel,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    // Day 13 — dark-theme `t.ink` (near-white) on the light-gold `late` cell
    // was ≈3.3:1. Force dark ink on gold cells in either theme; gold reads
    // as light everywhere so `AppColors.ink` clears AA in both.
    final isLateCell = statusAr == 'متأخّر';
    final textColor = isLateCell ? AppColors.ink : t.ink;
    final child = Container(
      decoration: BoxDecoration(
        color: color,
        borderRadius: BorderRadius.circular(6),
        border: isToday
            ? Border.all(color: AppColors.gold, width: 2)
            : Border.all(color: t.border),
      ),
      alignment: Alignment.center,
      child: Text(
        arabize(day),
        style: TextStyle(
          color: textColor,
          fontWeight: isToday ? FontWeight.w800 : FontWeight.w600,
          fontSize: 12,
          fontFeatures: const [FontFeature.tabularFigures()],
        ),
      ),
    );
    // Day 12 — Parallel-channel accessibility label. The visible cell only
    // renders a colored square + day number; TalkBack/color-blind users hear
    // "٧ سبتمبر ٢٠٢٥: حاضر" instead of just "7".
    final labeled = Semantics(
      button: onTap != null,
      label: '${arabize(day)} ${arabize(monthLabel)}: $statusAr${isToday ? '، اليوم' : ''}',
      excludeSemantics: true,
      child: child,
    );
    if (onTap == null) return labeled;
    return InkWell(
      borderRadius: BorderRadius.circular(6),
      onTap: onTap,
      child: labeled,
    );
  }
}

class _WeekdayLabel extends StatelessWidget {
  final String text;
  const _WeekdayLabel(this.text);
  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Text(
        text,
        textAlign: TextAlign.center,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          color: context.tokens.muted,
          fontSize: 10,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }
}

class _LegendDot extends StatelessWidget {
  final Color color;
  final String label;
  const _LegendDot({required this.color, required this.label});
  @override
  Widget build(BuildContext context) {
    // Day 12 — MergeSemantics collapses the color swatch + label into one SR
    // node so TalkBack reads "حاضر" (once) rather than pausing on the dot.
    return MergeSemantics(
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 10,
            height: 10,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(3),
            ),
          ),
          const SizedBox(width: 4),
          Text(
            label,
            style: TextStyle(
              color: context.tokens.muted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );
  }
}

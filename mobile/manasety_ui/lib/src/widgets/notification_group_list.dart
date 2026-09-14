import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../theme/arabize.dart';
import '../theme/colors.dart';
import '../theme/tokens.dart';

/// One notification, kept as a bare tuple so `manasety_ui` doesn't depend on
/// either app's model class. Callers `.map` their own model → this.
class NotificationCell {
  final int id;

  /// One of `"attendance" | "grade" | "invoice" | "material" | ...` — anything
  /// else falls back to a generic bell.
  final String kind;

  /// Pre-rendered human-friendly text.
  final String message;

  final DateTime createdAt;
  final bool unread;
  final VoidCallback? onTap;

  const NotificationCell({
    required this.id,
    required this.kind,
    required this.message,
    required this.createdAt,
    this.unread = false,
    this.onTap,
  });
}

/// Grouped, unread-aware notification feed used by both apps.
///
/// Sections: `اليوم`, `أمس`, `هذا الأسبوع`, then month-year for older.
/// Rows: tinted-circle icon (per-kind) + message + relative time (Arabic),
/// with a small red dot on the trailing edge when [NotificationCell.unread].
class NotificationGroupList extends StatelessWidget {
  final List<NotificationCell> items;
  final EdgeInsetsGeometry padding;

  const NotificationGroupList({
    super.key,
    required this.items,
    this.padding = const EdgeInsets.fromLTRB(16, 12, 16, 24),
  });

  @override
  Widget build(BuildContext context) {
    if (items.isEmpty) return const SizedBox.shrink();
    // Keep items in the caller-provided order (newest first). Bucket.
    final buckets = <String, List<NotificationCell>>{};
    final bucketOrder = <String>[];
    for (final n in items) {
      final key = _bucketKey(n.createdAt);
      if (!buckets.containsKey(key)) {
        buckets[key] = [];
        bucketOrder.add(key);
      }
      buckets[key]!.add(n);
    }
    return ListView(
      physics: const AlwaysScrollableScrollPhysics(),
      padding: padding,
      children: [
        for (final key in bucketOrder) ...[
          _GroupHeader(label: _labelFor(key), count: buckets[key]!.length),
          const SizedBox(height: 6),
          for (final n in buckets[key]!) ...[
            _Row(cell: n),
            const SizedBox(height: 8),
          ],
          const SizedBox(height: 12),
        ],
      ],
    );
  }

  /// Bucketing key: "today", "yesterday", "week", or "YYYY-MM" for older.
  static String _bucketKey(DateTime d) {
    final now = DateTime.now();
    final dayAgo = DateTime(now.year, now.month, now.day)
        .difference(DateTime(d.year, d.month, d.day))
        .inDays;
    if (dayAgo == 0) return 'today';
    if (dayAgo == 1) return 'yesterday';
    if (dayAgo <= 7) return 'week';
    return '${d.year}-${d.month.toString().padLeft(2, '0')}';
  }

  static String _labelFor(String key) {
    if (key == 'today') return 'اليوم';
    if (key == 'yesterday') return 'أمس';
    if (key == 'week') return 'هذا الأسبوع';
    // YYYY-MM
    final parts = key.split('-');
    if (parts.length == 2) {
      final year = int.parse(parts[0]);
      final month = int.parse(parts[1]);
      return DateFormat.yMMMM('ar').format(DateTime(year, month));
    }
    return key;
  }
}

class _GroupHeader extends StatelessWidget {
  final String label;
  final int count;
  const _GroupHeader({required this.label, required this.count});

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final primary = Theme.of(context).colorScheme.primary;
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 12, 4, 4),
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
            label,
            style: TextStyle(
              color: primary,
              fontWeight: FontWeight.w800,
              fontSize: 14,
            ),
          ),
          const SizedBox(width: 8),
          // Day 12 — bare number reads as just "٣" without unit; give it context.
          Semantics(
            label: '${arabize(count)} إشعارات',
            excludeSemantics: true,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
              decoration: BoxDecoration(
                color: t.subtleBg,
                borderRadius: BorderRadius.circular(10),
              ),
              // Day 13 — muted-on-subtleBg fails AA (3.9:1 light / 3.6:1 dark).
              // Use ink for the primary count; the pill is short + prominent
              // so the extra weight reads correctly.
              child: Text(
                arabize(count),
                style: TextStyle(
                  color: t.ink,
                  fontSize: 11,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Row extends StatelessWidget {
  final NotificationCell cell;
  const _Row({required this.cell});

  ({IconData icon, Color color}) _kindStyle() {
    switch (cell.kind) {
      case 'attendance':
      case 'absence':
        return (icon: Icons.event_available_outlined, color: AppColors.danger);
      case 'grade':
      case 'result_approved':
        return (icon: Icons.school_outlined, color: AppColors.gold);
      case 'invoice':
      case 'invoice_issued':
      case 'payment_received':
        return (icon: Icons.receipt_long_outlined, color: AppColors.success);
      case 'material':
        return (icon: Icons.menu_book_outlined, color: AppColors.sky);
      default:
        return (icon: Icons.notifications_outlined, color: AppColors.navy);
    }
  }

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final style = _kindStyle();
    final relTime = _relativeAr(cell.createdAt);

    final content = Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: cell.unread ? t.subtleBg : t.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: t.border),
      ),
      child: Row(
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: style.color.withValues(alpha: 0.14),
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Icon(style.icon, size: 20, color: style.color),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  cell.message,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: t.ink,
                    fontWeight: cell.unread ? FontWeight.w800 : FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  relTime,
                  style: TextStyle(color: t.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          if (cell.unread) ...[
            const SizedBox(width: 8),
            // Day 12 — the color-only dot now carries an SR label.
            Semantics(
              label: 'غير مقروء',
              child: Container(
                width: 8,
                height: 8,
                decoration: const BoxDecoration(
                  color: AppColors.danger,
                  shape: BoxShape.circle,
                ),
              ),
            ),
          ],
        ],
      ),
    );

    if (cell.onTap == null) return content;
    // Day 12 — announce as a button and fold the visual bits into one SR node.
    return Semantics(
      button: true,
      label: '${cell.message} — $relTime${cell.unread ? '، غير مقروء' : ''}',
      excludeSemantics: true,
      child: InkWell(
        onTap: cell.onTap,
        borderRadius: BorderRadius.circular(12),
        child: content,
      ),
    );
  }

  /// Arabic relative-time — الآن / منذ ٥ دقائق / منذ ساعتين / أمس ٣:٤٠ م / ...
  static String _relativeAr(DateTime d) {
    final now = DateTime.now();
    final diff = now.difference(d);
    if (diff.inSeconds < 60) return 'الآن';
    if (diff.inMinutes < 60) return 'منذ ${arabize(diff.inMinutes)} دقيقة';
    if (diff.inHours < 24) return 'منذ ${arabize(diff.inHours)} ساعة';
    if (diff.inDays == 1) {
      final t = DateFormat.jm('ar').format(d);
      return arabize('أمس $t');
    }
    if (diff.inDays < 7) return 'منذ ${arabize(diff.inDays)} أيام';
    return arabize(DateFormat.yMMMd('ar').format(d));
  }
}

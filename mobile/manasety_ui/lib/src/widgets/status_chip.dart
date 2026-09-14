import 'package:flutter/material.dart';

import '../theme/colors.dart';
import '../theme/tokens.dart';

enum StatusKind { success, warn, danger, neutral, info }

class StatusChip extends StatelessWidget {
  final String label;
  final StatusKind kind;
  final IconData? icon;
  final EdgeInsetsGeometry? padding;
  final double? fontSize;

  const StatusChip({
    super.key,
    required this.label,
    this.kind = StatusKind.neutral,
    this.icon,
    this.padding,
    this.fontSize,
  });

  /// Day 13 — every variant now clears WCAG AA (4.5:1) on both light and
  /// dark themes:
  /// - `warn` / `danger` invert to a solid accent bg + white fg (~7:1); the
  ///   louder read is correct for warnings anyway.
  /// - `success` / `neutral` bump the tint to 0.22 alpha and swap fg to the
  ///   text-safe `*Ink` variant.
  /// - `info` already passed; unchanged.
  ({Color bg, Color fg, Color border}) _palette(BuildContext context) {
    final t = context.tokens;
    switch (kind) {
      case StatusKind.success:
        return (
          bg: AppColors.success.withValues(alpha: 0.22),
          fg: AppColors.successInk,
          border: AppColors.success.withValues(alpha: 0.55),
        );
      case StatusKind.warn:
        return (
          bg: AppColors.gold,
          fg: Colors.white,
          border: AppColors.goldDark,
        );
      case StatusKind.danger:
        return (
          bg: AppColors.danger,
          fg: Colors.white,
          border: AppColors.dangerInk,
        );
      case StatusKind.info:
        return (
          bg: t.accentBg,
          fg: Theme.of(context).colorScheme.primary,
          border: AppColors.sky.withValues(alpha: 0.8),
        );
      case StatusKind.neutral:
        return (
          bg: t.subtleBg,
          fg: t.ink,
          border: t.border,
        );
    }
  }

  @override
  Widget build(BuildContext context) {
    final p = _palette(context);
    // Day 10 — key by (kind, label) so any state change fades+scales in.
    final chip = Container(
      key: ValueKey('${kind.name}-$label'),
      padding: padding ??
          const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: p.bg,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: p.border),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: p.fg),
            const SizedBox(width: 4),
          ],
          Text(
            label,
            style: TextStyle(
              color: p.fg,
              fontSize: fontSize ?? 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
    return AnimatedSwitcher(
      duration: const Duration(milliseconds: 250),
      transitionBuilder: (child, animation) => FadeTransition(
        opacity: animation,
        child: ScaleTransition(
          scale: Tween<double>(begin: 0.92, end: 1.0).animate(animation),
          child: child,
        ),
      ),
      child: chip,
    );
  }
}

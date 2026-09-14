import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/arabize.dart';
import '../theme/tokens.dart';

/// Compact hero stat — big colored value + small muted label + optional icon.
///
/// One-line usage:
///   StatTile(value: '92%', label: 'الحضور', icon: Icons.event_available)
///
/// Sizes itself to fill its parent (typical use is inside [StatRow] which
/// stretches three of these across the screen).
class StatTile extends StatelessWidget {
  /// The big number/text (e.g. `"92%"`, `"3 اليوم"`, `"—"`).
  final String value;

  /// The small caption underneath (e.g. `"الحضور"`).
  final String label;

  /// Optional icon rendered inline before the value.
  final IconData? icon;

  /// Accent color for the value + icon. Defaults to `colorScheme.primary`
  /// so the tile adapts to light/dark automatically.
  final Color? accent;

  final VoidCallback? onTap;

  const StatTile({
    super.key,
    required this.value,
    required this.label,
    this.icon,
    this.accent,
    this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final scheme = Theme.of(context).colorScheme;
    final accentColor = accent ?? scheme.primary;

    final content = Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 12),
      decoration: BoxDecoration(
        color: t.surface,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: t.border),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (icon != null) ...[
                Icon(icon, size: 16, color: accentColor),
                const SizedBox(width: 6),
              ],
              Flexible(
                child: Text(
                  arabize(value),   // auto-arabize numeric display
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    color: accentColor,
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                    fontFeatures: const [FontFeature.tabularFigures()],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            label,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: TextStyle(
              color: t.muted,
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ],
      ),
    );

    if (onTap == null) {
      // Non-interactive tile — still fold value + label into one SR node.
      return Semantics(
        container: true,
        label: '$label: ${arabize(value)}',
        excludeSemantics: true,
        child: content,
      );
    }
    return Semantics(
      button: true,
      label: '$label: ${arabize(value)}',
      excludeSemantics: true,
      child: InkWell(
        onTap: () {
          HapticFeedback.selectionClick();
          onTap!();
        },
        borderRadius: BorderRadius.circular(12),
        child: content,
      ),
    );
  }
}

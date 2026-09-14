import 'package:flutter/material.dart';

import '../theme/tokens.dart';

/// Circular avatar containing a centered icon, with a soft tinted background.
///
/// Used across every card that fronts a domain object — child, section,
/// material, subject. Consistent shape everywhere.
///
/// Colors adapt automatically:
///   - background = [tint] (usually a subject accent) at low alpha,
///     falling back to `context.tokens.accentBg`
///   - icon color = [tint] (or `colorScheme.primary` if omitted)
class TintedIconAvatar extends StatelessWidget {
  final IconData icon;
  final double size;
  final Color? tint;

  const TintedIconAvatar({
    super.key,
    required this.icon,
    this.size = 44,
    this.tint,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final scheme = Theme.of(context).colorScheme;
    final fg = tint ?? scheme.primary;
    final bg = tint == null
        ? t.accentBg
        : tint!.withValues(alpha: 0.14);
    final iconSize = size * 0.5;

    // Day 12 — Purely decorative reinforcement; the sibling text label
    // (subject / child name / etc.) already carries the meaning. Hide the
    // Icon+backdrop from TalkBack so the SR user isn't told "school" before
    // every subject name.
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: bg,
          shape: BoxShape.circle,
        ),
        alignment: Alignment.center,
        child: Icon(icon, size: iconSize, color: fg),
      ),
    );
  }
}

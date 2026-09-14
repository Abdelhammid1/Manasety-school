import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../theme/tokens.dart';

/// Card with a leading vertical accent rail — the signature card shape used
/// across every list in the apps for consistent visual DNA.
///
/// The rail communicates category / status at a glance (subject color,
/// today/upcoming, unread, etc). Content is whatever the caller passes.
class AccentRailCard extends StatelessWidget {
  /// Color of the leading 4-dp rail. If null the card renders without a rail
  /// (falls back to a normal bordered card).
  final Color? accent;

  /// Whether the rail should read as "prominent" — thicker + outlined border.
  final bool prominent;

  final VoidCallback? onTap;
  final Widget child;
  final EdgeInsetsGeometry padding;

  /// Day 12 — When [onTap] is set, this string labels the tappable card for
  /// TalkBack. Callers pass a summary like `'أحمد — الأول أ — الرقم …'`.
  /// If omitted, the card is still marked as a button but relies on the
  /// child content for its label.
  final String? semanticsLabel;

  const AccentRailCard({
    super.key,
    required this.child,
    this.accent,
    this.prominent = false,
    this.onTap,
    this.padding = const EdgeInsets.all(14),
    this.semanticsLabel,
  });

  @override
  Widget build(BuildContext context) {
    final t = context.tokens;
    final borderColor = prominent && accent != null
        ? accent!.withValues(alpha: 0.55)
        : t.border;
    final borderWidth = prominent ? 1.4 : 1.0;

    // IntrinsicHeight so the leading rail matches the height of the content
    // column. Without it, the rail Container(width: 4, no height) collapses
    // to zero and takes the whole Card down with it (Flutter layout gotcha
    // with CrossAxisAlignment.stretch on a Row with unbounded parent height).
    final card = Card(
      clipBehavior: Clip.antiAlias,   // clip the rail to the card's rounded corners
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: borderColor, width: borderWidth),
      ),
      child: IntrinsicHeight(
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            if (accent != null) Container(width: 4, color: accent),
            Expanded(
              child: Padding(padding: padding, child: child),
            ),
          ],
        ),
      ),
    );

    if (onTap == null) return card;
    final inkWell = InkWell(
      onTap: () {
        HapticFeedback.selectionClick();
        onTap!();
      },
      borderRadius: BorderRadius.circular(12),
      child: card,
    );
    // Day 12 — flag as button so TalkBack announces the tappable role.
    // When [semanticsLabel] is provided, we also collapse child content
    // into a single SR node with a caller-authored summary.
    if (semanticsLabel != null) {
      return Semantics(
        button: true,
        label: semanticsLabel,
        excludeSemantics: true,
        child: inkWell,
      );
    }
    return Semantics(button: true, child: inkWell);
  }
}

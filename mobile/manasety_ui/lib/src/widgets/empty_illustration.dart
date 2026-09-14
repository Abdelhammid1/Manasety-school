import 'package:flutter/material.dart';

import '../theme/colors.dart';
import '../theme/tokens.dart';

/// Empty-state illustration kinds. Each renders a small brand-composed
/// picture (tinted backdrop + Material icon + gold accent) instead of the
/// bare Material glyph the `EmptyState` widget renders by default.
enum ManasetyEmpty {
  family,
  calendar,
  book,
  receipt,
  bookmark,
  bell,
  classroom,
  generic,
}

/// Signature illustration shown when a screen has no data. Composed from
/// Flutter primitives so it adapts to light/dark automatically and needs
/// no extra dep.
class EmptyIllustration extends StatelessWidget {
  final ManasetyEmpty kind;
  final double size;

  const EmptyIllustration({
    super.key,
    required this.kind,
    this.size = 140,
  });

  @override
  Widget build(BuildContext context) {
    final Widget picture = switch (kind) {
      ManasetyEmpty.family => _family(context, size),
      ManasetyEmpty.calendar => _calendar(context, size),
      ManasetyEmpty.book => _book(context, size),
      ManasetyEmpty.receipt => _receipt(context, size),
      ManasetyEmpty.bookmark => _bookmark(context, size),
      ManasetyEmpty.bell => _bell(context, size),
      ManasetyEmpty.classroom => _classroom(context, size),
      ManasetyEmpty.generic => _generic(context, size),
    };
    // Day 12 — Decorative reinforcement only. EmptyState.title / description
    // beneath already carry the message; hide the composite from TalkBack so
    // it doesn't announce every Icon+Container primitive in turn.
    return ExcludeSemantics(child: picture);
  }
}

/// ── Primitives ──────────────────────────────────────────────────────────

Widget _circleBackdrop({required double size, required Color color}) {
  return Container(
    width: size,
    height: size,
    decoration: BoxDecoration(color: color, shape: BoxShape.circle),
  );
}

Widget _roundedBackdrop({
  required double size,
  required Color color,
  double radius = 20,
}) {
  return Container(
    width: size,
    height: size,
    decoration: BoxDecoration(
      color: color,
      borderRadius: BorderRadius.circular(radius),
    ),
  );
}

Widget _goldDot({double diameter = 10}) {
  return Container(
    width: diameter,
    height: diameter,
    decoration: const BoxDecoration(
      color: AppColors.gold,
      shape: BoxShape.circle,
    ),
  );
}

Widget _sparkle({double size = 12}) {
  // Small 4-pointed star via two crossed thin rectangles.
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        Container(
          width: size * 0.28,
          height: size,
          decoration: BoxDecoration(
            color: AppColors.gold,
            borderRadius: BorderRadius.circular(1),
          ),
        ),
        Container(
          width: size,
          height: size * 0.28,
          decoration: BoxDecoration(
            color: AppColors.gold,
            borderRadius: BorderRadius.circular(1),
          ),
        ),
      ],
    ),
  );
}

Color _bg(BuildContext ctx) => ctx.tokens.accentBg;
Color _accent(BuildContext ctx) => Theme.of(ctx).colorScheme.primary;

/// ── Illustrations ──────────────────────────────────────────────────────

Widget _family(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _circleBackdrop(size: size * 0.86, color: _bg(ctx)),
        Icon(Icons.family_restroom, size: size * 0.45, color: _accent(ctx)),
        Positioned(top: size * 0.10, right: size * 0.12, child: _sparkle(size: 14)),
        Positioned(bottom: size * 0.14, left: size * 0.10, child: _sparkle(size: 10)),
      ],
    ),
  );
}

Widget _calendar(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _roundedBackdrop(size: size * 0.82, color: _bg(ctx), radius: 18),
        // top gold tab
        Positioned(
          top: size * 0.10,
          child: Container(
            width: size * 0.30,
            height: size * 0.06,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(4),
            ),
          ),
        ),
        Icon(Icons.event_available_outlined, size: size * 0.44, color: _accent(ctx)),
        // check-tick badge bottom-right
        Positioned(
          bottom: size * 0.12,
          right: size * 0.12,
          child: Container(
            width: size * 0.18,
            height: size * 0.18,
            decoration: const BoxDecoration(
              color: AppColors.success,
              shape: BoxShape.circle,
            ),
            alignment: Alignment.center,
            child: Icon(Icons.check, size: size * 0.11, color: Colors.white),
          ),
        ),
      ],
    ),
  );
}

Widget _book(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _roundedBackdrop(size: size * 0.82, color: _bg(ctx), radius: 18),
        Icon(Icons.menu_book_outlined, size: size * 0.46, color: _accent(ctx)),
        // gold underline like a book divider
        Positioned(
          bottom: size * 0.17,
          child: Container(
            width: size * 0.34,
            height: 4,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
      ],
    ),
  );
}

Widget _receipt(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _roundedBackdrop(size: size * 0.82, color: _bg(ctx), radius: 16),
        Icon(Icons.receipt_long_outlined, size: size * 0.46, color: _accent(ctx)),
        // gold "stamp" square top-right
        Positioned(
          top: size * 0.14,
          right: size * 0.14,
          child: Container(
            width: size * 0.14,
            height: size * 0.14,
            decoration: BoxDecoration(
              color: AppColors.gold.withValues(alpha: 0.35),
              borderRadius: BorderRadius.circular(3),
              border: Border.all(color: AppColors.gold, width: 2),
            ),
          ),
        ),
      ],
    ),
  );
}

Widget _bookmark(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _roundedBackdrop(size: size * 0.82, color: _bg(ctx), radius: 18),
        Icon(Icons.bookmarks_outlined, size: size * 0.46, color: _accent(ctx)),
        // Gold ribbon flag top-right
        Positioned(
          top: size * 0.10,
          right: size * 0.14,
          child: Container(
            width: size * 0.10,
            height: size * 0.20,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: const BorderRadius.vertical(top: Radius.circular(3)),
            ),
          ),
        ),
      ],
    ),
  );
}

Widget _bell(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _circleBackdrop(size: size * 0.86, color: _bg(ctx)),
        Icon(Icons.notifications_outlined, size: size * 0.5, color: _accent(ctx)),
        // three sparkles around the bell
        Positioned(top: size * 0.08, right: size * 0.14, child: _sparkle(size: 12)),
        Positioned(top: size * 0.22, left: size * 0.10, child: _goldDot(diameter: 8)),
        Positioned(bottom: size * 0.16, right: size * 0.08, child: _sparkle(size: 10)),
      ],
    ),
  );
}

Widget _classroom(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _roundedBackdrop(size: size * 0.82, color: _bg(ctx), radius: 20),
        Icon(Icons.school_outlined, size: size * 0.5, color: _accent(ctx)),
        // Gold underline like a blackboard shelf
        Positioned(
          bottom: size * 0.15,
          child: Container(
            width: size * 0.40,
            height: 3,
            decoration: BoxDecoration(
              color: AppColors.gold,
              borderRadius: BorderRadius.circular(2),
            ),
          ),
        ),
      ],
    ),
  );
}

Widget _generic(BuildContext ctx, double size) {
  return SizedBox(
    width: size,
    height: size,
    child: Stack(
      alignment: Alignment.center,
      children: [
        _circleBackdrop(size: size * 0.86, color: _bg(ctx)),
        Icon(Icons.inbox_outlined, size: size * 0.5, color: _accent(ctx)),
        Positioned(bottom: size * 0.18, right: size * 0.18, child: _goldDot(diameter: 10)),
      ],
    ),
  );
}

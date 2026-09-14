import 'package:flutter/material.dart';

/// Mode-aware semantic color slots — the values that must flip between light
/// and dark themes. Brand-identity colors (navy, gold, sky, success, danger)
/// stay in [AppColors] because they're intentional accents that read on
/// either scaffold.
///
/// Registered on [ThemeData.extensions] by `AppTheme.light()` and
/// `AppTheme.dark()`; consumed via `context.tokens.ink` etc.
class ManasetyTokens extends ThemeExtension<ManasetyTokens> {
  /// Primary body text — near-black on light, near-white on dark.
  final Color ink;

  /// Secondary text (subtitles, hints, timestamps).
  final Color muted;

  /// Card / elevated surface fill.
  final Color surface;

  /// Scaffold background — one step behind [surface].
  final Color bg;

  /// Divider / outlined-container edge.
  final Color border;

  /// Soft accent fill used behind icons and info chips
  /// (was `AppColors.sky.withValues(alpha: 0.4)` before Day 2).
  final Color accentBg;

  /// Inert chip / disabled-fill background
  /// (was `AppColors.border` before Day 2).
  final Color subtleBg;

  const ManasetyTokens({
    required this.ink,
    required this.muted,
    required this.surface,
    required this.bg,
    required this.border,
    required this.accentBg,
    required this.subtleBg,
  });

  static const ManasetyTokens light = ManasetyTokens(
    ink: Color(0xFF111827),
    muted: Color(0xFF6B7280),
    surface: Color(0xFFFFFFFF),
    bg: Color(0xFFF7F8FA),
    border: Color(0xFFE5E7EB),
    accentBg: Color(0x66AED9E0), // sky @ 40%
    subtleBg: Color(0xFFE5E7EB),
  );

  static const ManasetyTokens dark = ManasetyTokens(
    ink: Color(0xFFF3F4F6),
    muted: Color(0xFF9CA3AF),
    surface: Color(0xFF1E293B),    // lighter, so cards clearly rise off scaffold
    bg: Color(0xFF0B1220),         // deep near-black scaffold
    border: Color(0xFF334155),     // more visible outline on dark surface
    accentBg: Color(0x33AED9E0),
    subtleBg: Color(0xFF334155),
  );

  @override
  ManasetyTokens copyWith({
    Color? ink,
    Color? muted,
    Color? surface,
    Color? bg,
    Color? border,
    Color? accentBg,
    Color? subtleBg,
  }) {
    return ManasetyTokens(
      ink: ink ?? this.ink,
      muted: muted ?? this.muted,
      surface: surface ?? this.surface,
      bg: bg ?? this.bg,
      border: border ?? this.border,
      accentBg: accentBg ?? this.accentBg,
      subtleBg: subtleBg ?? this.subtleBg,
    );
  }

  @override
  ManasetyTokens lerp(ThemeExtension<ManasetyTokens>? other, double t) {
    if (other is! ManasetyTokens) return this;
    return ManasetyTokens(
      ink: Color.lerp(ink, other.ink, t) ?? ink,
      muted: Color.lerp(muted, other.muted, t) ?? muted,
      surface: Color.lerp(surface, other.surface, t) ?? surface,
      bg: Color.lerp(bg, other.bg, t) ?? bg,
      border: Color.lerp(border, other.border, t) ?? border,
      accentBg: Color.lerp(accentBg, other.accentBg, t) ?? accentBg,
      subtleBg: Color.lerp(subtleBg, other.subtleBg, t) ?? subtleBg,
    );
  }

}

/// Ergonomic accessor: `context.tokens.ink` instead of
/// `Theme.of(context).extension<ManasetyTokens>()!.ink`.
extension ManasetyTokensX on BuildContext {
  ManasetyTokens get tokens => Theme.of(this).extension<ManasetyTokens>()!;
}

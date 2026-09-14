import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'colors.dart';

class AppTypography {
  /// Returns a Cairo-Arabic [TextTheme] with body/display text colored via the
  /// provided [bodyColor] / [displayColor]. Defaults to [AppColors.ink] so
  /// existing light-mode callers keep working; the dark theme passes the
  /// dark [ManasetyTokens.ink] so default `Text(...)` widgets read correctly
  /// on the dark scaffold.
  static TextTheme cairo(
    TextTheme base, {
    Color? bodyColor,
    Color? displayColor,
  }) {
    return GoogleFonts.cairoTextTheme(base).apply(
      bodyColor: bodyColor ?? AppColors.ink,
      displayColor: displayColor ?? AppColors.ink,
    );
  }
}

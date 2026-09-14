import 'package:flutter/material.dart';

import 'colors.dart';
import 'manasety_page_transitions.dart';
import 'tokens.dart';
import 'typography.dart';

/// Day 8 — global page-transitions theme shared by both light and dark modes.
const _pageTransitions = PageTransitionsTheme(builders: {
  TargetPlatform.android: ManasetyPageTransitionsBuilder(),
  TargetPlatform.iOS: ManasetyPageTransitionsBuilder(),
  TargetPlatform.fuchsia: ManasetyPageTransitionsBuilder(),
});

/// Day 12 — gold-tinted focus/hover/pressed overlay. Visible on both navy
/// (elevated) and white/gold (outlined/text) button surfaces. Restores a
/// clear focus ring for keyboard / D-pad / Bluetooth-keyboard users.
WidgetStateProperty<Color?> _focusOverlay() =>
    WidgetStateProperty.resolveWith((states) {
      if (states.contains(WidgetState.focused)) {
        return AppColors.gold.withValues(alpha: 0.20);
      }
      if (states.contains(WidgetState.hovered)) {
        return AppColors.gold.withValues(alpha: 0.08);
      }
      if (states.contains(WidgetState.pressed)) {
        return AppColors.gold.withValues(alpha: 0.14);
      }
      return null;
    });

class AppTheme {
  static ThemeData light() {
    final base = ThemeData(useMaterial3: true, brightness: Brightness.light);
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.navy,
      primary: AppColors.navy,
      secondary: AppColors.gold,
      tertiary: AppColors.sky,
      surface: AppColors.surface,
      error: AppColors.danger,
      brightness: Brightness.light,
    );

    return base.copyWith(
      colorScheme: scheme,
      scaffoldBackgroundColor: AppColors.bg,
      textTheme: AppTypography.cairo(base.textTheme),
      primaryTextTheme: AppTypography.cairo(base.primaryTextTheme),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: Colors.white,
          fontSize: 18,
          fontWeight: FontWeight.w700,
        ),
        iconTheme: IconThemeData(color: Colors.white),
      ),
      cardTheme: CardThemeData(
        elevation: 0,
        color: AppColors.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: const BorderSide(color: AppColors.border),
        ),
        margin: EdgeInsets.zero,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.navy,
          foregroundColor: Colors.white,
          textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 18),
        ).copyWith(overlayColor: _focusOverlay()),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.gold,
          side: const BorderSide(color: AppColors.gold, width: 1.4),
          textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
        ).copyWith(overlayColor: _focusOverlay()),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AppColors.navy)
            .copyWith(overlayColor: _focusOverlay()),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.navy, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.danger),
        ),
        labelStyle: const TextStyle(color: AppColors.muted),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.sky.withValues(alpha: 0.35),
        labelStyle: const TextStyle(color: AppColors.navy, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
        side: BorderSide.none,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      ),
      dividerTheme: const DividerThemeData(color: AppColors.border, thickness: 1, space: 1),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: AppColors.navy,
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.navy,
        contentTextStyle: TextStyle(color: Colors.white),
      ),
      pageTransitionsTheme: _pageTransitions,
      extensions: const [ManasetyTokens.light],
    );
  }

  /// Dark twin of [light]. Registered on `MaterialApp.darkTheme` alongside
  /// `themeMode: ThemeMode.system` so both apps flip automatically with the OS.
  ///
  /// Brand accents (navy AppBar, gold outlined buttons, navy elevated buttons)
  /// are intentionally preserved so brand recognition survives the theme flip.
  /// Everything scaffold/card/text/border-shaped comes from the dark
  /// [ManasetyTokens] and the M3 dark [ColorScheme].
  static ThemeData dark() {
    final base = ThemeData(useMaterial3: true, brightness: Brightness.dark);
    final scheme = ColorScheme.fromSeed(
      seedColor: AppColors.navy,
      primary: AppColors.navy,
      secondary: AppColors.gold,
      tertiary: AppColors.sky,
      surface: ManasetyTokens.dark.surface,
      error: AppColors.danger,
      brightness: Brightness.dark,
    );

    return base.copyWith(
      colorScheme: scheme,
      scaffoldBackgroundColor: ManasetyTokens.dark.bg,
      textTheme: AppTypography.cairo(
        base.textTheme,
        bodyColor: ManasetyTokens.dark.ink,
        displayColor: ManasetyTokens.dark.ink,
      ),
      primaryTextTheme: AppTypography.cairo(
        base.primaryTextTheme,
        bodyColor: ManasetyTokens.dark.ink,
        displayColor: ManasetyTokens.dark.ink,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: AppColors.navy,
        foregroundColor: Colors.white,
        elevation: 0,
        centerTitle: false,
        titleTextStyle: TextStyle(
          color: Colors.white,
          fontSize: 18,
          fontWeight: FontWeight.w700,
        ),
        iconTheme: IconThemeData(color: Colors.white),
      ),
      cardTheme: CardThemeData(
        elevation: 2,
        shadowColor: Colors.black,
        color: ManasetyTokens.dark.surface,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(12),
          side: BorderSide(color: ManasetyTokens.dark.border),
        ),
        margin: EdgeInsets.zero,
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: AppColors.navy,
          foregroundColor: Colors.white,
          textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          padding: const EdgeInsets.symmetric(vertical: 14, horizontal: 18),
        ).copyWith(overlayColor: _focusOverlay()),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: AppColors.gold,
          side: const BorderSide(color: AppColors.gold, width: 1.4),
          textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 14),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(10),
          ),
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
        ).copyWith(overlayColor: _focusOverlay()),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: AppColors.gold)
            .copyWith(overlayColor: _focusOverlay()),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: ManasetyTokens.dark.surface,
        contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: ManasetyTokens.dark.border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide(color: ManasetyTokens.dark.border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.gold, width: 1.6),
        ),
        errorBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: AppColors.danger),
        ),
        labelStyle: TextStyle(color: ManasetyTokens.dark.muted),
      ),
      chipTheme: ChipThemeData(
        backgroundColor: AppColors.sky.withValues(alpha: 0.15),
        labelStyle: const TextStyle(color: AppColors.sky, fontWeight: FontWeight.w600),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
        ),
        side: BorderSide.none,
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      ),
      dividerTheme: DividerThemeData(
        color: ManasetyTokens.dark.border,
        thickness: 1,
        space: 1,
      ),
      progressIndicatorTheme: const ProgressIndicatorThemeData(
        color: AppColors.gold, // gold reads better than navy on dark bg
      ),
      snackBarTheme: const SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: AppColors.navy,
        contentTextStyle: TextStyle(color: Colors.white),
      ),
      pageTransitionsTheme: _pageTransitions,
      extensions: const [ManasetyTokens.dark],
    );
  }
}

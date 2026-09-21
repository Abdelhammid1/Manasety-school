import 'package:flutter/material.dart';

/// Generic **Manasety K-12** brand — navy → blue → cyan gradient.
///
/// Ported verbatim from the Stitch design system exported on 2026-09-21.
/// Lives ALONGSIDE the legacy [AppColors] palette so `parent_app` and
/// `teacher_app` (which reference `AppColors.gold` etc.) keep building
/// unchanged. New apps (starting with `student_app`) should reference
/// [ManasetyBrand] directly; those two apps can migrate later without
/// blocking anyone.
class ManasetyBrand {
  ManasetyBrand._();

  // ── Primary gradient stops ───────────────────────────────────────
  static const Color navy = Color(0xFF1E3A8A);
  static const Color blue = Color(0xFF2563EB);
  static const Color cyan = Color(0xFF0099CC);

  /// The signature 3-stop gradient used on hero cards, primary CTAs,
  /// splash backgrounds, and any "brand moment" surface.
  ///
  /// Equivalent to
  /// `linear-gradient(135deg, #1E3A8A 0%, #2563EB 55%, #0099CC 100%)`.
  static const LinearGradient primaryGradient = LinearGradient(
    begin: Alignment.topRight,
    end: Alignment.bottomLeft,
    stops: [0.0, 0.55, 1.0],
    colors: [navy, blue, cyan],
  );

  // ── Semantic accents ────────────────────────────────────────────
  static const Color success = Color(0xFF10B981);
  static const Color warning = Color(0xFFF59E0B);
  static const Color error   = Color(0xFFEF4444);

  // ── Surfaces (light theme) ──────────────────────────────────────
  static const Color surface                 = Color(0xFFF8FAFC);
  static const Color surfaceContainerLowest  = Color(0xFFFFFFFF);
  static const Color surfaceContainerLow     = Color(0xFFF1F5F9);
  static const Color surfaceContainer        = Color(0xFFE2E8F0);

  // ── Text ────────────────────────────────────────────────────────
  static const Color onSurface        = Color(0xFF0F172A);
  static const Color onSurfaceVariant = Color(0xFF475569);
  static const Color outline          = Color(0xFF94A3B8);

  // ── Radii ───────────────────────────────────────────────────────
  static const double radiusMd  = 8.0;
  static const double radiusLg  = 12.0;
  static const double radiusXl  = 16.0;
  static const double radius2xl = 20.0;

  // ── Shadows ─────────────────────────────────────────────────────
  static const List<BoxShadow> shadowDefault = [
    BoxShadow(
      color: Color(0x0A000000),   // rgba(0,0,0,0.04)
      offset: Offset(0, 1),
      blurRadius: 8,
    ),
  ];
  static const List<BoxShadow> shadowRaised = [
    BoxShadow(
      color: Color(0x14000000),   // rgba(0,0,0,0.08)
      offset: Offset(0, 4),
      blurRadius: 16,
    ),
  ];

  // ── Bottom-tab active affordance ────────────────────────────────
  /// 3px underline shown under the active bottom-tab item.
  static const double tabActiveUnderline = 3.0;
}

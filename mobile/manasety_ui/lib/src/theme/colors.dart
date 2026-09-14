import 'package:flutter/material.dart';

/// ألوان هوية مؤسسة الشيخ صالح الشريف للتعليم القرآني.
class AppColors {
  static const navy = Color(0xFF001556);
  static const navyDark = Color(0xFF000B33);
  static const navySoft = Color(0xFF1A2D6C);
  static const gold = Color(0xFFD4AF37);
  static const goldDark = Color(0xFFB8941F);
  /// Day 12 hot-fix — deep brand-gold with ≈5:1 contrast on white/light
  /// surfaces. Use for TEXT that must read as "gold" (hero numbers, primary
  /// text-buttons, warning flash copy). Keep [gold] for borders/rails/tints
  /// where luminance doesn't matter.
  static const goldInk = Color(0xFF7A5B00);
  static const sky = Color(0xFFAED9E0);

  static const ink = Color(0xFF111827);
  static const muted = Color(0xFF6B7280);
  static const surface = Color(0xFFFFFFFF);
  static const bg = Color(0xFFF7F8FA);
  static const border = Color(0xFFE5E7EB);

  static const success = Color(0xFF16A34A);
  static const danger = Color(0xFFDC2626);
  static const warn = gold;

  /// Day 13 — text-safe siblings of [success] and [danger]. Use these when
  /// rendering the color on a tinted-of-the-same-color background (chips,
  /// pills, status text on flash cards) — the raw [success]/[danger] fail
  /// AA 4.5:1 on their own low-alpha tints. Bg tints can still use the
  /// bright originals.
  static const successInk = Color(0xFF0F7A37);   // ≈4.9:1 on white
  static const dangerInk  = Color(0xFFB01818);   // ≈5.5:1 on white
}

import 'package:flutter/material.dart';

/// Deterministic per-subject accent color + icon.
///
/// Same [subjectName] → same color/icon across every screen (sections list,
/// section detail, materials cards, timetable slots). Backed by an 8-hue
/// palette hashed from the UTF-16 code units of the Arabic name, plus a
/// curated icon map with a sensible book fallback.
///
/// Colors chosen to read on both light and dark scaffolds (medium saturation,
/// medium lightness).
class SubjectPalette {
  static const List<Color> _palette = [
    // Day 13 — three hues darkened (teal, amber-brown, steel) so the raw
    // palette color reads ≥4.5:1 on white/#F7F8FA when used directly as
    // text (subject_progress_bar avatar icon, timetable slot label).
    Color(0xFF276876), // teal (was #2E7D8F)
    Color(0xFF7B4B94), // purple
    Color(0xFF8F5300), // amber-brown (was #B86E00)
    Color(0xFF3F7A3F), // moss green
    Color(0xFFB84A6C), // rose
    Color(0xFF4F5D9F), // indigo
    Color(0xFF8B6B2F), // olive
    Color(0xFF376079), // steel blue (was #4B7F9A)
  ];

  static const Map<String, IconData> _iconMap = {
    'الرياضيات': Icons.calculate_outlined,
    'الفقه': Icons.balance,
    'القرآن': Icons.auto_stories_outlined,
    'الحديث': Icons.article_outlined,
    'التوحيد': Icons.wb_incandescent_outlined,
    'العقيدة': Icons.wb_incandescent_outlined,
    'اللغة العربية': Icons.abc,
    'العربية': Icons.abc,
    'اللغة الإنجليزية': Icons.translate,
    'الإنجليزية': Icons.translate,
    'العلوم': Icons.science_outlined,
    'الاجتماعيات': Icons.public,
    'التاريخ': Icons.history_edu_outlined,
    'الجغرافيا': Icons.map_outlined,
    'التربية الإسلامية': Icons.mosque_outlined,
    'التربية البدنية': Icons.sports_soccer,
    'الحاسوب': Icons.computer,
    'الفنون': Icons.palette_outlined,
  };

  static int _hash(String name) {
    // FNV-1a-ish over UTF-16 code units — Arabic-safe.
    var h = 0x811c9dc5;
    for (final u in name.codeUnits) {
      h = ((h ^ u) * 0x01000193) & 0x7fffffff;
    }
    return h;
  }

  /// Accent color for a subject name. Same input → same color across screens.
  static Color accent(String subjectName) {
    if (subjectName.isEmpty) return _palette[0];
    return _palette[_hash(subjectName) % _palette.length];
  }

  /// Icon for a subject name. Matches curated Arabic names (with or without
  /// prefix `-fx` fixture suffix) and falls back to a generic book icon.
  static IconData icon(String subjectName) {
    // Strip trailing `-fx` fixture suffix so fixture subjects share icons
    // with real ones (e.g. `الرياضيات-fx` → `الرياضيات`).
    final normalized = subjectName.replaceAll(RegExp(r'-fx$'), '').trim();
    return _iconMap[normalized] ?? Icons.menu_book_outlined;
  }
}

/// Ergonomic top-level helpers.
Color subjectAccent(String name) => SubjectPalette.accent(name);
IconData subjectIcon(String name) => SubjectPalette.icon(name);

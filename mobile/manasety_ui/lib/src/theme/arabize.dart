const List<String> _arDigits = [
  '٠', '١', '٢', '٣', '٤', '٥', '٦', '٧', '٨', '٩',
];

/// Convert every ASCII `0-9` in [v] (int, double, String, or anything else
/// whose `toString()` produces text) to its Arabic-Indic `٠-٩` counterpart.
/// Everything else passes through unchanged — percent signs, decimal points,
/// letters, spaces, currency symbols. Safe to call on already-arabized text.
///
/// Use for user-facing DISPLAY only — never wrap form inputs, IDs, or values
/// destined for the API (numeric keyboards and validators need Western digits).
String arabize(Object? v) {
  if (v == null) return '';
  final s = v.toString();
  final b = StringBuffer();
  for (final r in s.runes) {
    if (r >= 0x30 && r <= 0x39) {
      b.write(_arDigits[r - 0x30]);
    } else {
      b.writeCharCode(r);
    }
  }
  return b.toString();
}

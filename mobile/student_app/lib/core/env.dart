/// نقطة وصول الـ API لتطبيق الطالب.
///
/// شبيه بـ env الخاص بـ parent_app: يقرأ `--dart-define=API_BASE=…`
/// أو يقع افتراضياً على النسخة المنشورة.
class Env {
  static const String _override =
      String.fromEnvironment('API_BASE', defaultValue: '');

  static String get apiBase {
    if (_override.isNotEmpty) return _override;
    return 'https://school.manasety.ai/api';
  }

  static const String appFlavor = 'student';
  static const String institutionNameAr = 'مدرستي';
}

/// نقطة وصول الـ API.
///
/// Day 13 (v3) — default is the deployed backend for **all** builds (debug
/// and release, physical device and emulator). Point at localhost only when
/// you're actively developing against a local Flask instance:
///
///     flutter run --dart-define=API_BASE=http://localhost:5050/api
///
/// On a physical Android device with a local Flask, also run:
///
///     adb reverse tcp:5050 tcp:5050
///
/// so `localhost:5050` on the phone bridges to your workstation.
class Env {
  static const String _override =
      String.fromEnvironment('API_BASE', defaultValue: '');

  static String get apiBase {
    if (_override.isNotEmpty) return _override;
    return 'https://school.manasety.ai/api';
  }

  static const String appFlavor = 'teacher';

  static const String institutionNameAr =
      'مؤسسة الشيخ صالح الشريف للتعليم القرآني';
}

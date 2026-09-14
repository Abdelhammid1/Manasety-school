import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/attendance/presentation/take_attendance_screen.dart';
import '../../features/auth/application/auth_controller.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/grades/presentation/grade_picker_screen.dart';
import '../../features/grades/presentation/grade_entry_screen.dart';
import '../../features/home/presentation/main_scaffold.dart';
import '../../features/materials/presentation/upload_material_screen.dart';
import '../../features/profile/presentation/change_password_screen.dart';
import '../../features/sections/presentation/section_detail_screen.dart';
import '../../features/splash/presentation/welcome_splash_screen.dart';
import 'package:manasety_ui/manasety_ui.dart';
import 'routes.dart';

final routerProvider = Provider<GoRouter>((ref) {
  final authNotifier = _AuthRouterListenable(ref);
  ref.onDispose(authNotifier.dispose);

  return GoRouter(
    initialLocation: Routes.welcome,
    refreshListenable: authNotifier,
    redirect: (context, state) {
      final auth = ref.read(authControllerProvider);
      final loc = state.matchedLocation;
      if (auth is AuthBooting) return null;
      // Day 13 (v3) — the welcome splash owns navigation for its own
      // lifetime; don't redirect away while it's showing.
      if (loc == Routes.welcome) return null;
      final loggedIn = auth is Authenticated;
      if (!loggedIn && loc != Routes.login) return Routes.login;
      if (loggedIn && loc == Routes.login) return Routes.home;
      return null;
    },
    routes: [
      GoRoute(path: Routes.welcome, builder: (_, __) => const WelcomeSplashScreen()),
      GoRoute(path: Routes.login, builder: (_, __) => const LoginScreen()),
      GoRoute(path: Routes.home, builder: (_, __) => const MainScaffold()),
      GoRoute(
        path: '/sections/:id',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          return SectionDetailScreen(sectionId: id);
        },
      ),
      GoRoute(
        path: '/sections/:id/attendance',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          final dateStr = state.uri.queryParameters['date'];
          final date = dateStr != null ? DateTime.tryParse(dateStr) : null;
          return TakeAttendanceScreen(sectionId: id, initialDate: date);
        },
      ),
      GoRoute(
        path: '/sections/:id/grades',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          return GradePickerScreen(sectionId: id);
        },
      ),
      GoRoute(
        path: '/sections/:id/grades/entry',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          final q = state.uri.queryParameters;
          return GradeEntryScreen(
            sectionId: id,
            termId: int.parse(q['term']!),
            subjectId: int.parse(q['subject']!),
            componentId: int.parse(q['component']!),
            componentName: q['name'] ?? '',
            maxScore: double.tryParse(q['max'] ?? '') ?? 100.0,
          );
        },
      ),
      GoRoute(
        path: '/materials/upload',
        builder: (_, __) => const UploadMaterialScreen(),
      ),
      GoRoute(
        path: '/profile/change-password',
        builder: (_, __) => const ChangePasswordScreen(),
      ),
    ],
    errorBuilder: (_, state) => Scaffold(
      body: Center(
        child: Text(
          'مسار غير معروف: ${state.uri}',
          style: const TextStyle(color: AppColors.danger),
        ),
      ),
    ),
  );
});

class _AuthRouterListenable extends ChangeNotifier {
  _AuthRouterListenable(Ref ref) {
    _sub = ref.listen<AuthState>(authControllerProvider, (_, __) {
      notifyListeners();
    }, fireImmediately: false);
  }
  late final ProviderSubscription<AuthState> _sub;

  @override
  void dispose() {
    _sub.close();
    super.dispose();
  }
}

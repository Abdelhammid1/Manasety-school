import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/application/auth_controller.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/children/presentation/child_detail_screen.dart';
import '../../features/children/presentation/children_screen.dart';
import '../../features/profile/presentation/profile_screen.dart';
import '../../features/profile/presentation/edit_profile_screen.dart';
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
      GoRoute(path: Routes.home, builder: (_, __) => const ChildrenScreen()),
      GoRoute(path: Routes.profile, builder: (_, __) => const ProfileScreen()),
      GoRoute(path: Routes.profileEdit, builder: (_, __) => const EditProfileScreen()),
      GoRoute(
        path: '/children/:id',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          // Sprint 10 audit — support ?tab=attendance for FCM deep-links.
          final tab = tabIndexFromName(state.uri.queryParameters['tab']);
          return ChildDetailScreen(childId: id, initialTab: tab);
        },
      ),
      // Sprint 10 audit — dedicated sub-paths so FCM push data.route matches:
      //   /children/<id>/attendance
      //   /children/<id>/results
      //   /children/<id>/invoices
      //   /children/<id>/materials
      //   /children/<id>/notifications
      GoRoute(
        path: '/children/:id/:tab',
        builder: (_, state) {
          final id = int.parse(state.pathParameters['id']!);
          final tab = tabIndexFromName(state.pathParameters['tab']);
          return ChildDetailScreen(childId: id, initialTab: tab);
        },
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

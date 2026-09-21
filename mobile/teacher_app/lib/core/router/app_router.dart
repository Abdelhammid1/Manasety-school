import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/announcements/presentation/announcements_screen.dart';
import '../../features/assignments/presentation/assignments_screen.dart';
import '../../features/attendance/presentation/attendance_hub_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/gradebook/presentation/gradebook_hub_screen.dart';
import '../../features/home/presentation/home_screen.dart';
import '../../features/materials/presentation/materials_screen.dart';
import '../../features/messages/presentation/messages_screen.dart';
import '../../features/profile/presentation/profile_screen.dart';
import '../../features/quizzes/presentation/quizzes_screen.dart';
import '../../features/sections/presentation/sections_screen.dart';
import '../../features/splash/presentation/splash_screen.dart';
import '../../features/timetable/presentation/timetable_screen.dart';
import '../../shared/layout/teacher_shell.dart';
import 'routes.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: Routes.splash,
    routes: [
      GoRoute(path: Routes.splash, builder: (_, __) => const SplashScreen()),
      GoRoute(path: Routes.login,  builder: (_, __) => const LoginScreen()),

      ShellRoute(
        builder: (context, state, child) => TeacherShell(child: child),
        routes: [
          GoRoute(path: Routes.home,       builder: (_, __) => const HomeScreen()),
          GoRoute(path: Routes.sections,   builder: (_, __) => const SectionsScreen()),
          GoRoute(path: Routes.attendance, builder: (_, __) => const AttendanceHubScreen()),
          GoRoute(path: Routes.gradebook,  builder: (_, __) => const GradebookHubScreen()),
          GoRoute(path: Routes.profile,    builder: (_, __) => const ProfileScreen()),
        ],
      ),

      GoRoute(path: Routes.timetable,      builder: (_, __) => const TimetableScreen()),
      GoRoute(path: Routes.assignments,    builder: (_, __) => const AssignmentsScreen()),
      GoRoute(path: Routes.quizzes,        builder: (_, __) => const QuizzesScreen()),
      GoRoute(path: Routes.announcements,  builder: (_, __) => const AnnouncementsScreen()),
      GoRoute(path: Routes.messages,       builder: (_, __) => const MessagesScreen()),
      GoRoute(path: Routes.materials,      builder: (_, __) => const MaterialsScreen()),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('صفحة غير موجودة: ${state.uri}')),
    ),
  );
});

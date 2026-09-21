import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/announcements/presentation/announcement_detail_screen.dart';
import '../../features/announcements/presentation/announcements_screen.dart';
import '../../features/assignments/presentation/assignment_attempt_screen.dart';
import '../../features/assignments/presentation/assignments_screen.dart';
import '../../features/assignments/presentation/quiz_attempt_screen.dart';
import '../../features/attendance/presentation/attendance_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/courses/presentation/course_detail_screen.dart';
import '../../features/courses/presentation/courses_screen.dart';
import '../../features/courses/presentation/lesson_viewer_screen.dart';
import '../../features/grades/presentation/grades_screen.dart';
import '../../features/home/presentation/home_screen.dart';
import '../../features/profile/presentation/profile_screen.dart';
import '../../features/splash/presentation/splash_screen.dart';
import '../../features/timetable/presentation/timetable_screen.dart';
import '../../shared/layout/student_shell.dart';
import 'routes.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: Routes.splash,
    routes: [
      GoRoute(path: Routes.splash, builder: (_, __) => const SplashScreen()),
      GoRoute(path: Routes.login,  builder: (_, __) => const LoginScreen()),

      // Bottom-tab shell — one navigator per tab so back-stack is isolated.
      ShellRoute(
        builder: (context, state, child) => StudentShell(child: child),
        routes: [
          GoRoute(path: Routes.home,        builder: (_, __) => const HomeScreen()),
          GoRoute(path: Routes.courses,     builder: (_, __) => const CoursesScreen()),
          GoRoute(path: Routes.assignments, builder: (_, __) => const AssignmentsScreen()),
          GoRoute(path: Routes.timetable,   builder: (_, __) => const TimetableScreen()),
          GoRoute(path: Routes.profile,     builder: (_, __) => const ProfileScreen()),
        ],
      ),

      // Detail screens outside the shell (push over the tab bar).
      GoRoute(path: Routes.announcements, builder: (_, __) => const AnnouncementsScreen()),
      GoRoute(path: Routes.attendance,    builder: (_, __) => const AttendanceScreen()),
      GoRoute(path: Routes.grades,        builder: (_, __) => const GradesScreen()),
      GoRoute(
        path: Routes.courseDetail,
        builder: (_, state) => CourseDetailScreen(
          courseId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: Routes.lessonViewer,
        builder: (_, state) => LessonViewerScreen(
          lessonId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: Routes.assignmentAttempt,
        builder: (_, state) => AssignmentAttemptScreen(
          assignmentId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: Routes.quizAttempt,
        builder: (_, state) => QuizAttemptScreen(
          quizId: int.parse(state.pathParameters['id']!)),
      ),
      GoRoute(
        path: Routes.announcementDetail,
        builder: (_, state) => AnnouncementDetailScreen(
          announcementId: int.parse(state.pathParameters['id']!)),
      ),
    ],
    errorBuilder: (context, state) => Scaffold(
      body: Center(child: Text('صفحة غير موجودة: ${state.uri}')),
    ),
  );
});

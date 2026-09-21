/// Named routes for the Student app — kept as constants so widgets can
/// reference them without stringly-typed literals.
class Routes {
  Routes._();

  static const splash = '/';
  static const login = '/login';

  // Shell tabs
  static const home = '/home';
  static const courses = '/courses';
  static const assignments = '/assignments';
  static const timetable = '/timetable';
  static const profile = '/profile';

  // Nested
  static const courseDetail = '/courses/:id';
  static const lessonViewer = '/lessons/:id';
  static const assignmentAttempt = '/assignments/:id/attempt';
  static const quizAttempt = '/quizzes/:id/attempt';
  static const announcements = '/announcements';
  static const announcementDetail = '/announcements/:id';
  static const attendance = '/attendance';
  static const grades = '/grades';
}

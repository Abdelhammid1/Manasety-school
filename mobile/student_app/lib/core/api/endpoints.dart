/// Student-app API endpoints — mirror of `app/blueprints/api/routes.py`
/// under the `/student/*` prefix.
class Endpoints {
  Endpoints._();

  // ── Auth ──────────────────────────────────────────────────
  static const login = '/auth/login';
  static const me = '/me';
  static const changePassword = '/auth/change-password';

  // ── Home / dashboard rollup ───────────────────────────────
  static const studentHome = '/student/home';

  // ── Courses / lessons ─────────────────────────────────────
  static const courses = '/student/courses';
  static String courseDetail(int id) => '/student/courses/$id';
  static String lessonView(int id) => '/student/lessons/$id';

  // ── Assignments & quizzes ─────────────────────────────────
  static const assignments = '/student/assignments';
  static String assignmentDetail(int id) => '/student/assignments/$id';
  static String assignmentSubmit(int id) => '/student/assignments/$id/submit';
  static const quizzes = '/student/quizzes';
  static String quizAttempt(int id) => '/student/quizzes/$id/attempt';
  static String quizSubmit(int id) => '/student/quizzes/$id/submit';

  // ── Schedule / attendance ─────────────────────────────────
  static const timetable = '/student/schedule';
  static const attendance = '/student/attendance';

  // ── Grades / report card ──────────────────────────────────
  static const grades = '/student/grades';
  static String reportCard(int termId) => '/student/report-card/$termId';

  // ── Announcements ─────────────────────────────────────────
  static const announcements = '/student/announcements';
  static String announcementDetail(int id) => '/student/announcements/$id';
}

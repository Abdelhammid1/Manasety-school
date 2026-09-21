/// Teacher-app API endpoints. Existing routes in
/// `app/blueprints/api/routes.py` cover schedule, sections, students,
/// attendance, grades, materials, upload. Additional endpoints for
/// home rollup, assignments/quizzes CRUD, announcements, messages are
/// added in the same session.
class Endpoints {
  Endpoints._();

  // Auth / me
  static const login = '/auth/login';
  static const me = '/me';

  // Home rollup — today periods + pending grading + new messages
  static const teacherHome = '/teacher/home';

  // Sections / students
  static const sections = '/teacher/sections';
  static String sectionSchedule(int id) => '/teacher/section/$id/schedule';
  static const students = '/teacher/students';

  // Attendance
  static const attendanceMark   = '/teacher/attendance';   // POST
  static const attendanceExisting = '/teacher/attendance'; // GET

  // Grades
  static const gradesRecord = '/teacher/grades';   // POST
  static const gradesExisting = '/teacher/grades'; // GET
  static const components = '/teacher/components';

  // Assignments
  static const assignments = '/teacher/assignments';
  static String assignmentDetail(int id) => '/teacher/assignments/$id';
  static String assignmentSubmissions(int id) => '/teacher/assignments/$id/submissions';
  static String assignmentGrade(int id, int studentId) =>
      '/teacher/assignments/$id/submissions/$studentId/grade';

  // Quizzes
  static const quizzes = '/teacher/quizzes';
  static String quizStats(int id) => '/teacher/quizzes/$id/stats';

  // Announcements
  static const announcements = '/teacher/announcements';

  // Messages
  static const messages = '/teacher/messages';
  static String messageThread(int threadId) => '/teacher/messages/$threadId';

  // Materials
  static const materials = '/teacher/materials';
  static const materialUpload = '/teacher/upload';

  // Schedule + terms
  static const schedule = '/teacher/schedule';
  static const terms = '/teacher/terms';
}

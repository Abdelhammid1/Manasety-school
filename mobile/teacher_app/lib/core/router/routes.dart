/// Named routes for the Teacher app.
class Routes {
  Routes._();

  static const splash = '/';
  static const login = '/login';

  // Shell tabs
  static const home = '/home';
  static const sections = '/sections';
  static const attendance = '/attendance';
  static const gradebook = '/gradebook';
  static const profile = '/profile';

  // Nested
  static const sectionDetail = '/sections/:id';
  static const studentList = '/sections/:id/students';
  static const studentDetail = '/students/:id';
  static const attendanceMark = '/attendance/mark/:sectionId';
  static const assignments = '/assignments';
  static const assignmentDetail = '/assignments/:id';
  static const gradeSubmission = '/assignments/:id/submissions/:studentId';
  static const quizzes = '/quizzes';
  static const quizStats = '/quizzes/:id/stats';
  static const announcements = '/announcements';
  static const announcementCreate = '/announcements/new';
  static const messages = '/messages';
  static const messageThread = '/messages/:id';
  static const timetable = '/timetable';
  static const materials = '/materials';
}

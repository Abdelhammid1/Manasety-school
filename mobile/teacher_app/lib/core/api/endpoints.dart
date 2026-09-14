/// ثوابت مسارات الـ API.
class Endpoints {
  // المصادقة
  static const login = '/auth/login';
  static const me = '/me';
  static const changePassword = '/auth/change-password';
  static const deviceToken = '/auth/device-token';

  // المعلم
  static const teacherSections = '/teacher/sections';
  static const teacherSchedule = '/teacher/schedule';
  static const teacherTerms = '/teacher/terms';
  static const teacherStudents = '/teacher/students';
  static const teacherAttendance = '/teacher/attendance';
  static const teacherGrades = '/teacher/grades';
  static const teacherComponents = '/teacher/components';
  static const teacherMaterials = '/teacher/materials';
  static const teacherUpload = '/teacher/upload';
  static String teacherSectionSchedule(int id) =>
      '/teacher/section/$id/schedule';

  // ولي الأمر (للاتساق فقط؛ تطبيق المعلم لا يستخدمها)
  static const parentChildren = '/parent/children';
  static const parentNotifications = '/parent/notifications';
  static String parentChildAttendance(int id) =>
      '/parent/child/$id/attendance';
  static String parentChildResults(int id) => '/parent/child/$id/results';
  static String parentChildInvoices(int id) => '/parent/child/$id/invoices';
  static String parentChildMaterials(int id) =>
      '/parent/child/$id/materials';
  static String parentChildSchedule(int id) =>
      '/parent/child/$id/schedule';

  // الإشعارات
  static String notificationRead(int id) => '/notifications/$id/read';
}

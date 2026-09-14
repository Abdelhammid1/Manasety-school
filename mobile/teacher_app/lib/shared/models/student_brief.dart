class StudentBrief {
  final int enrollmentId;
  final int studentId;
  final String permanentCode;
  final String fullName;

  const StudentBrief({
    required this.enrollmentId,
    required this.studentId,
    required this.permanentCode,
    required this.fullName,
  });

  factory StudentBrief.fromJson(Map<String, dynamic> j) => StudentBrief(
        enrollmentId: j['enrollment_id'] as int,
        studentId: j['student_id'] as int,
        permanentCode: (j['permanent_code'] ?? '') as String,
        fullName: (j['full_name'] ?? '') as String,
      );
}

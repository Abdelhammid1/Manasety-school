import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class AssignmentItem {
  final int id;
  final String title, instructions;
  final double maxScore;
  final bool isPublished, allowLate;
  final String? dueAt, createdAt, courseTitle, subject, grade;
  final int submissionCount, ungradedCount;
  const AssignmentItem({
    required this.id, required this.title, required this.instructions,
    required this.maxScore, this.isPublished = false, this.allowLate = true,
    this.dueAt, this.createdAt, this.courseTitle, this.subject, this.grade,
    this.submissionCount = 0, this.ungradedCount = 0,
  });
  factory AssignmentItem.fromJson(Map<String, dynamic> j) => AssignmentItem(
    id: (j['id'] as num).toInt(),
    title: j['title'] as String? ?? '',
    instructions: j['instructions'] as String? ?? '',
    maxScore: (j['max_score'] as num?)?.toDouble() ?? 0,
    isPublished: j['is_published'] as bool? ?? false,
    allowLate: j['allow_late'] as bool? ?? true,
    dueAt: j['due_at'] as String?,
    createdAt: j['created_at'] as String?,
    courseTitle: j['course_title'] as String?,
    subject: j['subject'] as String?,
    grade: j['grade'] as String?,
    submissionCount: (j['submission_count'] as num?)?.toInt() ?? 0,
    ungradedCount: (j['ungraded_count'] as num?)?.toInt() ?? 0,
  );
}

class SubmissionItem {
  final int studentId;
  final String? studentName, permanentCode, submittedAt, feedback;
  final double? score, maxScore;
  final bool hasBody, hasFile, isGraded;
  const SubmissionItem({
    required this.studentId, this.studentName, this.permanentCode,
    this.submittedAt, this.score, this.maxScore, this.feedback,
    this.hasBody = false, this.hasFile = false, this.isGraded = false,
  });
  factory SubmissionItem.fromJson(Map<String, dynamic> j) => SubmissionItem(
    studentId: (j['student_id'] as num).toInt(),
    studentName: j['student_name'] as String?,
    permanentCode: j['permanent_code'] as String?,
    submittedAt: j['submitted_at'] as String?,
    score: (j['score'] as num?)?.toDouble(),
    maxScore: (j['max_score'] as num?)?.toDouble(),
    feedback: j['feedback'] as String?,
    hasBody: j['has_body'] as bool? ?? false,
    hasFile: j['has_file'] as bool? ?? false,
    isGraded: j['is_graded'] as bool? ?? false,
  );
}

class AssignmentsRepository {
  AssignmentsRepository(this._dio);
  final Dio _dio;
  Future<List<AssignmentItem>> list() async {
    final r = await _dio.get(Endpoints.assignments);
    return ((r.data as Map)['assignments'] as List)
      .map((e) => AssignmentItem.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<List<SubmissionItem>> submissions(int id) async {
    final r = await _dio.get(Endpoints.assignmentSubmissions(id));
    return ((r.data as Map)['submissions'] as List)
      .map((e) => SubmissionItem.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<double> grade({
    required int assignmentId, required int studentId,
    required double score, String? feedback,
  }) async {
    final r = await _dio.post(Endpoints.assignmentGrade(assignmentId, studentId),
      data: {'score': score, if (feedback != null) 'feedback': feedback});
    return ((r.data as Map)['score'] as num).toDouble();
  }
}

final assignmentsRepositoryProvider = Provider<AssignmentsRepository>((ref) =>
    AssignmentsRepository(ref.watch(dioProvider)));

final assignmentsProvider = FutureProvider.autoDispose<List<AssignmentItem>>((ref) =>
    ref.watch(assignmentsRepositoryProvider).list());

final assignmentSubmissionsProvider =
  FutureProvider.autoDispose.family<List<SubmissionItem>, int>((ref, id) =>
    ref.watch(assignmentsRepositoryProvider).submissions(id));

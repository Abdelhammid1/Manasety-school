import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class AssignmentBrief {
  final int id;
  final String title;
  final String? subject;
  final String? dueAt;
  final String status;      // not_started | submitted | graded
  final double? score;
  const AssignmentBrief({required this.id, required this.title, this.subject,
    this.dueAt, required this.status, this.score});
  factory AssignmentBrief.fromJson(Map<String, dynamic> j) => AssignmentBrief(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    subject: j['subject'] as String?, dueAt: j['due_at'] as String?,
    status: j['status'] as String? ?? 'not_started',
    score: (j['score'] as num?)?.toDouble(),
  );
}

class QuizBrief {
  final int id;
  final String title;
  final String? subject;
  final int? durationMinutes;
  final String? opensAt;
  final String? closesAt;
  final String status;      // not_started | in_progress | submitted | graded
  final double? score;
  const QuizBrief({required this.id, required this.title, this.subject,
    this.durationMinutes, this.opensAt, this.closesAt,
    required this.status, this.score});
  factory QuizBrief.fromJson(Map<String, dynamic> j) => QuizBrief(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    subject: j['subject'] as String?,
    durationMinutes: (j['duration_minutes'] as num?)?.toInt(),
    opensAt: j['opens_at'] as String?, closesAt: j['closes_at'] as String?,
    status: j['status'] as String? ?? 'not_started',
    score: (j['score'] as num?)?.toDouble(),
  );
}

class ChoiceOption {
  final int id;
  final String label;
  const ChoiceOption({required this.id, required this.label});
  factory ChoiceOption.fromJson(Map<String, dynamic> j) =>
      ChoiceOption(id: j['id'] as int, label: j['label'] as String? ?? '');
}

class AttemptQuestion {
  final int id;
  final String kind;     // mcq | tf | short | essay
  final String prompt;
  final double? points;
  final List<ChoiceOption> choices;
  const AttemptQuestion({required this.id, required this.kind, required this.prompt,
    this.points, this.choices = const []});
  factory AttemptQuestion.fromJson(Map<String, dynamic> j) => AttemptQuestion(
    id: j['id'] as int, kind: j['kind'] as String? ?? 'mcq',
    prompt: j['prompt'] as String? ?? '',
    points: (j['points'] as num?)?.toDouble(),
    choices: ((j['choices'] as List?) ?? [])
        .map((e) => ChoiceOption.fromJson((e as Map).cast<String, dynamic>())).toList(),
  );
}

class AssignmentDetail {
  final int id;
  final String title;
  final String instructions;
  final String? dueAt;
  final double? maxScore;
  final List<AttemptQuestion> questions;
  final Map<String, dynamic>? submission;   // {id, body, submitted_at, score, feedback}
  const AssignmentDetail({required this.id, required this.title,
    required this.instructions, this.dueAt, this.maxScore,
    this.questions = const [], this.submission});
  factory AssignmentDetail.fromJson(Map<String, dynamic> j) => AssignmentDetail(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    instructions: j['instructions'] as String? ?? '',
    dueAt: j['due_at'] as String?, maxScore: (j['max_score'] as num?)?.toDouble(),
    questions: ((j['questions'] as List?) ?? [])
        .map((e) => AttemptQuestion.fromJson((e as Map).cast<String, dynamic>())).toList(),
    submission: j['submission'] == null
        ? null : (j['submission'] as Map).cast<String, dynamic>(),
  );
}

class QuizAttemptDetail {
  final int id;
  final String title;
  final String description;
  final int? durationMinutes;
  final List<AttemptQuestion> questions;
  const QuizAttemptDetail({required this.id, required this.title,
    required this.description, this.durationMinutes,
    this.questions = const []});
  factory QuizAttemptDetail.fromJson(Map<String, dynamic> j) {
    final q = (j['quiz'] as Map).cast<String, dynamic>();
    return QuizAttemptDetail(
      id: q['id'] as int, title: q['title'] as String? ?? '',
      description: q['description'] as String? ?? '',
      durationMinutes: (q['duration_minutes'] as num?)?.toInt(),
      questions: ((j['questions'] as List?) ?? [])
          .map((e) => AttemptQuestion.fromJson((e as Map).cast<String, dynamic>())).toList(),
    );
  }
}

class AssignmentsRepository {
  AssignmentsRepository(this._dio);
  final Dio _dio;

  Future<List<AssignmentBrief>> listAssignments() async {
    final r = await _dio.get(Endpoints.assignments);
    return ((r.data['assignments'] as List?) ?? [])
        .map((e) => AssignmentBrief.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<List<QuizBrief>> listQuizzes() async {
    final r = await _dio.get(Endpoints.quizzes);
    return ((r.data['quizzes'] as List?) ?? [])
        .map((e) => QuizBrief.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<AssignmentDetail> assignment(int id) async {
    final r = await _dio.get(Endpoints.assignmentDetail(id));
    return AssignmentDetail.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<QuizAttemptDetail> quizAttempt(int id) async {
    final r = await _dio.get(Endpoints.quizAttempt(id));
    return QuizAttemptDetail.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<void> submitAssignment(int id, {required Map<int, dynamic> answers,
      String body = '', String? fileUrl}) async {
    await _dio.post(Endpoints.assignmentSubmit(id), data: {
      'answers': answers.map((k, v) => MapEntry(k.toString(), v)),
      'body': body, 'file_url': fileUrl ?? '',
    });
  }

  Future<Map<String, dynamic>> submitQuiz(int id, {required Map<int, dynamic> answers}) async {
    final r = await _dio.post(Endpoints.quizSubmit(id), data: {
      'answers': answers.map((k, v) => MapEntry(k.toString(), v)),
    });
    return (r.data as Map).cast<String, dynamic>();
  }
}

final assignmentsRepositoryProvider = Provider<AssignmentsRepository>((ref) {
  return AssignmentsRepository(ref.watch(dioProvider));
});

final assignmentsListProvider = FutureProvider.autoDispose<List<AssignmentBrief>>((ref) {
  return ref.watch(assignmentsRepositoryProvider).listAssignments();
});

final quizzesListProvider = FutureProvider.autoDispose<List<QuizBrief>>((ref) {
  return ref.watch(assignmentsRepositoryProvider).listQuizzes();
});

final assignmentDetailProvider = FutureProvider.autoDispose.family<AssignmentDetail, int>((ref, id) {
  return ref.watch(assignmentsRepositoryProvider).assignment(id);
});

final quizAttemptProvider = FutureProvider.autoDispose.family<QuizAttemptDetail, int>((ref, id) {
  return ref.watch(assignmentsRepositoryProvider).quizAttempt(id);
});

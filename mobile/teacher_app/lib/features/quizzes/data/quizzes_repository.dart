import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class QuizItem {
  final int id;
  final String title, description;
  final bool isPublished;
  final String? opensAt, closesAt, courseTitle, subject, grade;
  final int? durationMinutes, maxAttempts, questionCount, attemptCount;
  const QuizItem({
    required this.id, required this.title, required this.description,
    this.isPublished = false,
    this.opensAt, this.closesAt, this.courseTitle, this.subject, this.grade,
    this.durationMinutes, this.maxAttempts, this.questionCount, this.attemptCount,
  });
  factory QuizItem.fromJson(Map<String, dynamic> j) => QuizItem(
    id: (j['id'] as num).toInt(),
    title: j['title'] as String? ?? '',
    description: j['description'] as String? ?? '',
    isPublished: j['is_published'] as bool? ?? false,
    opensAt: j['opens_at'] as String?,
    closesAt: j['closes_at'] as String?,
    courseTitle: j['course_title'] as String?,
    subject: j['subject'] as String?,
    grade: j['grade'] as String?,
    durationMinutes: (j['duration_minutes'] as num?)?.toInt(),
    maxAttempts: (j['max_attempts'] as num?)?.toInt(),
    questionCount: (j['question_count'] as num?)?.toInt(),
    attemptCount: (j['attempt_count'] as num?)?.toInt(),
  );
}

class QuizStats {
  final QuizItem quiz;
  final int attempts;
  final double average, highest, lowest;
  final List<Map<String, dynamic>> students;
  const QuizStats({required this.quiz, required this.attempts,
    required this.average, required this.highest, required this.lowest,
    required this.students});
}

class QuizzesRepository {
  QuizzesRepository(this._dio);
  final Dio _dio;
  Future<List<QuizItem>> list() async {
    final r = await _dio.get(Endpoints.quizzes);
    return ((r.data as Map)['quizzes'] as List)
      .map((e) => QuizItem.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
  Future<QuizStats> stats(int id) async {
    final r = await _dio.get(Endpoints.quizStats(id));
    final d = (r.data as Map).cast<String, dynamic>();
    return QuizStats(
      quiz: QuizItem.fromJson((d['quiz'] as Map).cast<String, dynamic>()),
      attempts: (d['attempts'] as num).toInt(),
      average: (d['average'] as num?)?.toDouble() ?? 0,
      highest: (d['highest'] as num?)?.toDouble() ?? 0,
      lowest:  (d['lowest'] as num?)?.toDouble() ?? 0,
      students: ((d['students'] as List?) ?? []).cast<Map<String, dynamic>>(),
    );
  }
}

final quizzesRepositoryProvider = Provider<QuizzesRepository>((ref) =>
    QuizzesRepository(ref.watch(dioProvider)));

final quizzesProvider = FutureProvider.autoDispose<List<QuizItem>>((ref) =>
    ref.watch(quizzesRepositoryProvider).list());

final quizStatsProvider =
  FutureProvider.autoDispose.family<QuizStats, int>((ref, id) =>
    ref.watch(quizzesRepositoryProvider).stats(id));

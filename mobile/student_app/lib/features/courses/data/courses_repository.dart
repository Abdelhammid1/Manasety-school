import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class CourseBrief {
  final int id;
  final String title;
  final String? subject;
  final String? teacher;
  final int totalLessons;
  final String? coverUrl;
  const CourseBrief({required this.id, required this.title,
    this.subject, this.teacher, this.totalLessons = 0, this.coverUrl});
  factory CourseBrief.fromJson(Map<String, dynamic> j) => CourseBrief(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    subject: j['subject'] as String?, teacher: j['teacher'] as String?,
    totalLessons: (j['total_lessons'] as num?)?.toInt() ?? 0,
    coverUrl: j['cover_url'] as String?,
  );
}

class LessonBrief {
  final int id;
  final String title;
  final String kind;
  final int? durationMinutes;
  final String? mediaUrl;
  const LessonBrief({required this.id, required this.title, required this.kind,
    this.durationMinutes, this.mediaUrl});
  factory LessonBrief.fromJson(Map<String, dynamic> j) => LessonBrief(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    kind: j['kind'] as String? ?? 'text',
    durationMinutes: (j['duration_minutes'] as num?)?.toInt(),
    mediaUrl: j['media_url'] as String?,
  );
}

class UnitBlock {
  final int id;
  final String title;
  final List<LessonBrief> lessons;
  const UnitBlock({required this.id, required this.title, required this.lessons});
  factory UnitBlock.fromJson(Map<String, dynamic> j) => UnitBlock(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    lessons: ((j['lessons'] as List?) ?? [])
        .map((e) => LessonBrief.fromJson((e as Map).cast<String, dynamic>())).toList(),
  );
}

class CourseDetail {
  final int id;
  final String title;
  final String? subject;
  final String? teacher;
  final List<UnitBlock> units;
  final List<LessonBrief> orphanLessons;
  const CourseDetail({required this.id, required this.title, this.subject,
    this.teacher, this.units = const [], this.orphanLessons = const []});
  factory CourseDetail.fromJson(Map<String, dynamic> j) {
    final c = (j['course'] as Map).cast<String, dynamic>();
    return CourseDetail(
      id: c['id'] as int, title: c['title'] as String? ?? '',
      subject: c['subject'] as String?, teacher: c['teacher'] as String?,
      units: ((j['units'] as List?) ?? [])
          .map((e) => UnitBlock.fromJson((e as Map).cast<String, dynamic>())).toList(),
      orphanLessons: ((j['orphan_lessons'] as List?) ?? [])
          .map((e) => LessonBrief.fromJson((e as Map).cast<String, dynamic>())).toList(),
    );
  }
}

class LessonView {
  final int id;
  final int courseId;
  final int? unitId;
  final String title;
  final String kind;
  final String body;
  final String? mediaUrl;
  final int? durationMinutes;
  const LessonView({required this.id, required this.courseId, this.unitId,
    required this.title, required this.kind, required this.body,
    this.mediaUrl, this.durationMinutes});
  factory LessonView.fromJson(Map<String, dynamic> j) => LessonView(
    id: j['id'] as int, courseId: j['course_id'] as int,
    unitId: (j['unit_id'] as num?)?.toInt(),
    title: j['title'] as String? ?? '', kind: j['kind'] as String? ?? 'text',
    body: j['body'] as String? ?? '', mediaUrl: j['media_url'] as String?,
    durationMinutes: (j['duration_minutes'] as num?)?.toInt(),
  );
}

class CoursesRepository {
  CoursesRepository(this._dio);
  final Dio _dio;

  Future<List<CourseBrief>> list() async {
    final r = await _dio.get(Endpoints.courses);
    return ((r.data['courses'] as List?) ?? [])
        .map((e) => CourseBrief.fromJson((e as Map).cast<String, dynamic>()))
        .toList();
  }

  Future<CourseDetail> detail(int id) async {
    final r = await _dio.get(Endpoints.courseDetail(id));
    return CourseDetail.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<LessonView> lesson(int id) async {
    final r = await _dio.get(Endpoints.lessonView(id));
    return LessonView.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final coursesRepositoryProvider = Provider<CoursesRepository>((ref) {
  return CoursesRepository(ref.watch(dioProvider));
});

final coursesListProvider = FutureProvider.autoDispose<List<CourseBrief>>((ref) {
  return ref.watch(coursesRepositoryProvider).list();
});

final courseDetailProvider = FutureProvider.autoDispose.family<CourseDetail, int>((ref, id) {
  return ref.watch(coursesRepositoryProvider).detail(id);
});

final lessonViewProvider = FutureProvider.autoDispose.family<LessonView, int>((ref, id) {
  return ref.watch(coursesRepositoryProvider).lesson(id);
});

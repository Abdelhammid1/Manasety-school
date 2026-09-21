import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

/// Data-classes for the /student/home rollup — kept intentionally simple:
/// dumb JSON containers, no Freezed/Codegen so the app boots without any
/// build_runner step.
class HomeStats {
  final double? gpaPct;
  final double? attendancePct;
  final int assignmentsSubmitted;
  final int assignmentsTotal;
  const HomeStats({this.gpaPct, this.attendancePct,
    this.assignmentsSubmitted = 0, this.assignmentsTotal = 0});
  factory HomeStats.fromJson(Map<String, dynamic> j) => HomeStats(
    gpaPct: (j['gpa_pct'] as num?)?.toDouble(),
    attendancePct: (j['attendance_pct'] as num?)?.toDouble(),
    assignmentsSubmitted: (j['assignments_submitted'] as num?)?.toInt() ?? 0,
    assignmentsTotal:     (j['assignments_total']     as num?)?.toInt() ?? 0,
  );
}

class TodayPeriod {
  final int id;
  final String? day;
  final int dayOrder;
  final int periodOrder;
  final String? periodName;
  final String? start;
  final String? end;
  final String? subject;
  final String? teacher;
  final String? room;
  const TodayPeriod({
    required this.id, this.day, this.dayOrder = 0, this.periodOrder = 0,
    this.periodName, this.start, this.end, this.subject, this.teacher, this.room,
  });
  factory TodayPeriod.fromJson(Map<String, dynamic> j) => TodayPeriod(
    id: j['id'] as int,
    day: j['day'] as String?, dayOrder: (j['day_order'] as num?)?.toInt() ?? 0,
    periodOrder: (j['period_order'] as num?)?.toInt() ?? 0,
    periodName: j['period_name'] as String?,
    start: j['start'] as String?, end: j['end'] as String?,
    subject: j['subject'] as String?, teacher: j['teacher'] as String?,
    room: j['room'] as String?,
  );
}

class UpcomingItem {
  final int id;
  final String title;
  final String kind;        // assignment | quiz
  final String? dueAt;
  final String? subject;
  const UpcomingItem({required this.id, required this.title, required this.kind,
    this.dueAt, this.subject});
  factory UpcomingItem.fromJson(Map<String, dynamic> j) => UpcomingItem(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    kind: j['kind'] as String? ?? 'assignment',
    dueAt: j['due_at'] as String?, subject: j['subject'] as String?,
  );
}

class AnnouncementPreview {
  final int id;
  final String title;
  final String preview;
  final String? createdAt;
  const AnnouncementPreview({required this.id, required this.title,
    required this.preview, this.createdAt});
  factory AnnouncementPreview.fromJson(Map<String, dynamic> j) => AnnouncementPreview(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    preview: j['preview'] as String? ?? '', createdAt: j['created_at'] as String?,
  );
}

class HomeData {
  final Map<String, dynamic> student;   // id, full_name, permanent_code, class
  final HomeStats stats;
  final List<TodayPeriod> todayPeriods;
  final List<UpcomingItem> upcoming;
  final List<AnnouncementPreview> announcements;
  const HomeData({required this.student, required this.stats,
    required this.todayPeriods, required this.upcoming,
    required this.announcements});
  factory HomeData.fromJson(Map<String, dynamic> j) => HomeData(
    student: (j['student'] as Map).cast<String, dynamic>(),
    stats: HomeStats.fromJson((j['stats'] as Map).cast<String, dynamic>()),
    todayPeriods: ((j['today_periods'] as List?) ?? [])
        .map((e) => TodayPeriod.fromJson((e as Map).cast<String, dynamic>())).toList(),
    upcoming: ((j['upcoming'] as List?) ?? [])
        .map((e) => UpcomingItem.fromJson((e as Map).cast<String, dynamic>())).toList(),
    announcements: ((j['announcements'] as List?) ?? [])
        .map((e) => AnnouncementPreview.fromJson((e as Map).cast<String, dynamic>())).toList(),
  );
}

class HomeRepository {
  HomeRepository(this._dio);
  final Dio _dio;

  Future<HomeData> fetch() async {
    final r = await _dio.get(Endpoints.studentHome);
    return HomeData.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final homeRepositoryProvider = Provider<HomeRepository>((ref) {
  return HomeRepository(ref.watch(dioProvider));
});

final homeDataProvider = FutureProvider.autoDispose<HomeData>((ref) async {
  return ref.watch(homeRepositoryProvider).fetch();
});

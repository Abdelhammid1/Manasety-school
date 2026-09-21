import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class TeacherStats {
  final int todayPeriodCount;
  final int pendingGrading;
  final int studentCount;
  final int sectionCount;
  const TeacherStats({this.todayPeriodCount = 0, this.pendingGrading = 0,
    this.studentCount = 0, this.sectionCount = 0});
  factory TeacherStats.fromJson(Map<String, dynamic> j) => TeacherStats(
    todayPeriodCount: (j['today_period_count'] as num?)?.toInt() ?? 0,
    pendingGrading:   (j['pending_grading']    as num?)?.toInt() ?? 0,
    studentCount:     (j['student_count']      as num?)?.toInt() ?? 0,
    sectionCount:     (j['section_count']      as num?)?.toInt() ?? 0,
  );
}

class TodayPeriod {
  final int id;
  final String? day; final String? subject; final String? section; final String? room;
  final String? start; final String? end; final String? periodName;
  final int dayOrder; final int periodOrder;
  const TodayPeriod({required this.id, this.day, this.subject, this.section,
    this.room, this.start, this.end, this.periodName,
    this.dayOrder = 0, this.periodOrder = 0});
  factory TodayPeriod.fromJson(Map<String, dynamic> j) => TodayPeriod(
    id: (j['id'] as num).toInt(),
    day: j['day'] as String?, subject: j['subject'] as String?,
    section: j['section'] as String?, room: j['room'] as String?,
    start: j['start'] as String?, end: j['end'] as String?,
    periodName: j['period_name'] as String?,
    dayOrder: (j['day_order'] as num?)?.toInt() ?? 0,
    periodOrder: (j['period_order'] as num?)?.toInt() ?? 0,
  );
}

class PendingGradingItem {
  final int id; final String title; final String? subject; final int ungradedCount;
  const PendingGradingItem({required this.id, required this.title,
    this.subject, this.ungradedCount = 0});
  factory PendingGradingItem.fromJson(Map<String, dynamic> j) => PendingGradingItem(
    id: (j['id'] as num).toInt(),
    title: j['title'] as String? ?? '',
    subject: j['subject'] as String?,
    ungradedCount: (j['ungraded_count'] as num?)?.toInt() ?? 0,
  );
}

class RecentMessage {
  final int id; final String from; final String subject; final String preview; final String? createdAt;
  const RecentMessage({required this.id, required this.from, required this.subject,
    required this.preview, this.createdAt});
  factory RecentMessage.fromJson(Map<String, dynamic> j) => RecentMessage(
    id: (j['id'] as num).toInt(),
    from: j['from'] as String? ?? '',
    subject: j['subject'] as String? ?? '',
    preview: j['preview'] as String? ?? '',
    createdAt: j['created_at'] as String?,
  );
}

class TeacherHomeData {
  final Map<String, dynamic> teacher;
  final TeacherStats stats;
  final List<TodayPeriod> todayPeriods;
  final List<PendingGradingItem> pendingGrading;
  final List<RecentMessage> recentMessages;
  const TeacherHomeData({required this.teacher, required this.stats,
    this.todayPeriods = const [], this.pendingGrading = const [],
    this.recentMessages = const []});
  factory TeacherHomeData.fromJson(Map<String, dynamic> j) => TeacherHomeData(
    teacher: (j['teacher'] as Map).cast<String, dynamic>(),
    stats: TeacherStats.fromJson((j['stats'] as Map).cast<String, dynamic>()),
    todayPeriods: ((j['today_periods'] as List?) ?? [])
        .map((e) => TodayPeriod.fromJson((e as Map).cast<String, dynamic>())).toList(),
    pendingGrading: ((j['pending_grading'] as List?) ?? [])
        .map((e) => PendingGradingItem.fromJson((e as Map).cast<String, dynamic>())).toList(),
    recentMessages: ((j['recent_messages'] as List?) ?? [])
        .map((e) => RecentMessage.fromJson((e as Map).cast<String, dynamic>())).toList(),
  );
}

class HomeRepository {
  HomeRepository(this._dio);
  final Dio _dio;
  Future<TeacherHomeData> fetch() async {
    final r = await _dio.get(Endpoints.teacherHome);
    return TeacherHomeData.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final homeRepositoryProvider = Provider<HomeRepository>((ref) =>
    HomeRepository(ref.watch(dioProvider)));

final homeDataProvider = FutureProvider.autoDispose<TeacherHomeData>((ref) =>
    ref.watch(homeRepositoryProvider).fetch());

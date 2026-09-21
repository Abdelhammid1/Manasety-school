/// Small repos + providers for the remaining student screens where the
/// data shape is trivial (timetable, attendance, grades, announcements,
/// report card). Kept in one file to reduce boilerplate.
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/dio_client.dart';
import '../../core/api/endpoints.dart';

// ── Timetable ─────────────────────────────────────────────────

class SchedulePeriod {
  final String? day;
  final int dayOrder;
  final int periodOrder;
  final String? periodName;
  final String? start;
  final String? end;
  final String? subject;
  final String? teacher;
  final String? room;
  const SchedulePeriod({
    this.day, this.dayOrder = 0, this.periodOrder = 0,
    this.periodName, this.start, this.end,
    this.subject, this.teacher, this.room,
  });
  factory SchedulePeriod.fromJson(Map<String, dynamic> j) => SchedulePeriod(
    day: j['day'] as String?, dayOrder: (j['day_order'] as num?)?.toInt() ?? 0,
    periodOrder: (j['period_order'] as num?)?.toInt() ?? 0,
    periodName: j['period_name'] as String?,
    start: j['start'] as String?, end: j['end'] as String?,
    subject: j['subject'] as String?, teacher: j['teacher'] as String?,
    room: j['room'] as String?,
  );
}

// ── Attendance ────────────────────────────────────────────────

class AttendanceRow {
  final String? date;
  final String status;
  final String? reason;
  const AttendanceRow({this.date, required this.status, this.reason});
  factory AttendanceRow.fromJson(Map<String, dynamic> j) => AttendanceRow(
    date: j['date'] as String?, status: j['status'] as String? ?? '',
    reason: j['reason'] as String?,
  );
}

// ── Grades ────────────────────────────────────────────────────

class GradeRow {
  final int id;
  final String? term;
  final String? subject;
  final String? component;
  final double? score;
  final double? max;
  const GradeRow({required this.id, this.term, this.subject,
    this.component, this.score, this.max});
  factory GradeRow.fromJson(Map<String, dynamic> j) => GradeRow(
    id: j['id'] as int, term: j['term'] as String?, subject: j['subject'] as String?,
    component: j['component'] as String?,
    score: (j['score'] as num?)?.toDouble(),
    max:   (j['max']   as num?)?.toDouble(),
  );
}

class GradesResponse {
  final List<GradeRow> entries;
  final double? overallPct;
  const GradesResponse({required this.entries, this.overallPct});
  factory GradesResponse.fromJson(Map<String, dynamic> j) => GradesResponse(
    entries: ((j['entries'] as List?) ?? [])
        .map((e) => GradeRow.fromJson((e as Map).cast<String, dynamic>())).toList(),
    overallPct: j['year_result'] != null
        ? ((j['year_result'] as Map)['overall_percent'] as num?)?.toDouble()
        : null,
  );
}

// ── Announcements ─────────────────────────────────────────────

class AnnouncementRow {
  final int id;
  final String title;
  final String body;
  final String? author;
  final String? createdAt;
  const AnnouncementRow({required this.id, required this.title,
    required this.body, this.author, this.createdAt});
  factory AnnouncementRow.fromJson(Map<String, dynamic> j) => AnnouncementRow(
    id: j['id'] as int, title: j['title'] as String? ?? '',
    body: j['body'] as String? ?? '',
    author: j['author'] as String?, createdAt: j['created_at'] as String?,
  );
}

// ── Report Card ───────────────────────────────────────────────

class ReportSubject {
  final int subjectId;
  final String? subject;
  final double awarded;
  final double max;
  final double? pct;
  final List<Map<String, dynamic>> components;
  const ReportSubject({required this.subjectId, this.subject,
    required this.awarded, required this.max, this.pct, this.components = const []});
  factory ReportSubject.fromJson(Map<String, dynamic> j) => ReportSubject(
    subjectId: (j['subject_id'] as num).toInt(),
    subject: j['subject'] as String?,
    awarded: (j['awarded'] as num?)?.toDouble() ?? 0,
    max:     (j['max']     as num?)?.toDouble() ?? 0,
    pct:     (j['pct']     as num?)?.toDouble(),
    components: ((j['components'] as List?) ?? [])
        .map((e) => (e as Map).cast<String, dynamic>()).toList(),
  );
}

class ReportCard {
  final List<ReportSubject> subjects;
  final double? overallPct;
  const ReportCard({required this.subjects, this.overallPct});
  factory ReportCard.fromJson(Map<String, dynamic> j) => ReportCard(
    subjects: ((j['subjects'] as List?) ?? [])
        .map((e) => ReportSubject.fromJson((e as Map).cast<String, dynamic>())).toList(),
    overallPct: j['summary'] != null
        ? ((j['summary'] as Map)['overall_pct'] as num?)?.toDouble()
        : null,
  );
}

// ── Repositories + providers ──────────────────────────────────

class MiscRepository {
  MiscRepository(this._dio);
  final Dio _dio;

  Future<List<SchedulePeriod>> schedule() async {
    final r = await _dio.get(Endpoints.timetable);
    return ((r.data['schedule'] as List?) ?? [])
        .map((e) => SchedulePeriod.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<List<AttendanceRow>> attendance() async {
    final r = await _dio.get(Endpoints.attendance);
    return ((r.data['attendance'] as List?) ?? [])
        .map((e) => AttendanceRow.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<GradesResponse> grades() async {
    final r = await _dio.get(Endpoints.grades);
    return GradesResponse.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<List<AnnouncementRow>> announcements() async {
    final r = await _dio.get(Endpoints.announcements);
    return ((r.data['announcements'] as List?) ?? [])
        .map((e) => AnnouncementRow.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<AnnouncementRow> announcement(int id) async {
    final r = await _dio.get(Endpoints.announcementDetail(id));
    return AnnouncementRow.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<ReportCard> reportCard(int termId) async {
    final r = await _dio.get(Endpoints.reportCard(termId));
    return ReportCard.fromJson((r.data as Map).cast<String, dynamic>());
  }
}

final miscRepositoryProvider = Provider<MiscRepository>((ref) =>
    MiscRepository(ref.watch(dioProvider)));

final scheduleProvider = FutureProvider.autoDispose<List<SchedulePeriod>>((ref)
    => ref.watch(miscRepositoryProvider).schedule());
final attendanceProvider = FutureProvider.autoDispose<List<AttendanceRow>>((ref)
    => ref.watch(miscRepositoryProvider).attendance());
final gradesProvider = FutureProvider.autoDispose<GradesResponse>((ref)
    => ref.watch(miscRepositoryProvider).grades());
final announcementsProvider = FutureProvider.autoDispose<List<AnnouncementRow>>((ref)
    => ref.watch(miscRepositoryProvider).announcements());
final announcementDetailProvider = FutureProvider.autoDispose.family<AnnouncementRow, int>(
    (ref, id) => ref.watch(miscRepositoryProvider).announcement(id));
final reportCardProvider = FutureProvider.autoDispose.family<ReportCard, int>(
    (ref, termId) => ref.watch(miscRepositoryProvider).reportCard(termId));

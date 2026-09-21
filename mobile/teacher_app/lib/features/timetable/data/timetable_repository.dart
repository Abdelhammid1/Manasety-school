import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class ScheduleSlot {
  final int dayId, periodId, sectionId, subjectId;
  final String dayName, periodName;
  final String startTime, endTime;
  final String sectionName, subjectName;
  const ScheduleSlot({
    required this.dayId, required this.periodId,
    required this.sectionId, required this.subjectId,
    required this.dayName, required this.periodName,
    required this.startTime, required this.endTime,
    required this.sectionName, required this.subjectName,
  });
  factory ScheduleSlot.fromJson(Map<String, dynamic> j) => ScheduleSlot(
    dayId: (j['day_id'] as num).toInt(),
    periodId: (j['period_id'] as num).toInt(),
    sectionId: (j['section_id'] as num).toInt(),
    subjectId: (j['subject_id'] as num).toInt(),
    dayName: j['day_name'] as String? ?? '',
    periodName: j['period_name'] as String? ?? '',
    startTime: j['start_time'] as String? ?? '',
    endTime: j['end_time'] as String? ?? '',
    sectionName: j['section_name'] as String? ?? '',
    subjectName: j['subject_name'] as String? ?? '',
  );
}

class TimetableRepository {
  TimetableRepository(this._dio);
  final Dio _dio;
  Future<List<ScheduleSlot>> slots() async {
    final r = await _dio.get(Endpoints.schedule);
    return ((r.data as Map)['slots'] as List)
      .map((e) => ScheduleSlot.fromJson((e as Map).cast<String, dynamic>())).toList();
  }
}

final timetableRepositoryProvider = Provider<TimetableRepository>((ref) =>
    TimetableRepository(ref.watch(dioProvider)));

final timetableProvider = FutureProvider.autoDispose<List<ScheduleSlot>>((ref) =>
    ref.watch(timetableRepositoryProvider).slots());

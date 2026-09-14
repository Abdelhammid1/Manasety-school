import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import 'package:manasety_ui/manasety_ui.dart';
final scheduleRepositoryProvider = Provider<ScheduleRepository>((ref) {
  return ScheduleRepository(ref.watch(dioProvider));
});

class ScheduleRepository {
  final Dio _dio;
  ScheduleRepository(this._dio);

  Future<List<ScheduleSlot>> teacherWeekly() async {
    try {
      final r = await _dio.get(Endpoints.teacherSchedule);
      return _parse(r.data);
    } catch (e) {
      throw toApi(e);
    }
  }

  Future<List<ScheduleSlot>> forSection(int sectionId) async {
    try {
      final r = await _dio.get(Endpoints.teacherSectionSchedule(sectionId));
      return _parse(r.data);
    } catch (e) {
      throw toApi(e);
    }
  }

  List<ScheduleSlot> _parse(dynamic data) {
    final raw = (data['slots'] as List?) ?? const [];
    return raw
        .map((e) => ScheduleSlot.fromJson(e as Map<String, dynamic>))
        .toList();
  }
}

final teacherScheduleProvider =
    FutureProvider.autoDispose<List<ScheduleSlot>>((ref) {
  return ref.watch(scheduleRepositoryProvider).teacherWeekly();
});

final sectionScheduleProvider =
    FutureProvider.autoDispose.family<List<ScheduleSlot>, int>((ref, id) {
  return ref.watch(scheduleRepositoryProvider).forSection(id);
});

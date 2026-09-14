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

  Future<List<ScheduleSlot>> forChild(int studentId) async {
    try {
      final r = await _dio.get(Endpoints.parentChildSchedule(studentId));
      final raw = (r.data['slots'] as List?) ?? const [];
      return raw
          .map((e) => ScheduleSlot.fromJson(e as Map<String, dynamic>))
          .toList();
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childScheduleProvider =
    FutureProvider.autoDispose.family<List<ScheduleSlot>, int>((ref, id) {
  return ref.watch(scheduleRepositoryProvider).forChild(id);
});

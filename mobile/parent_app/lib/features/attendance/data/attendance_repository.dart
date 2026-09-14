import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/attendance.dart';

final attendanceRepositoryProvider = Provider<AttendanceRepository>((ref) {
  return AttendanceRepository(ref.watch(dioProvider));
});

class AttendanceRepository {
  final Dio _dio;
  AttendanceRepository(this._dio);

  Future<ChildAttendance> forChild(int studentId) async {
    try {
      final r = await _dio.get(Endpoints.parentChildAttendance(studentId));
      final summary = AttendanceSummary.fromJson(
          r.data['summary'] as Map<String, dynamic>);
      final raw = (r.data['records'] as List?) ?? const [];
      final records = raw
          .map((e) => AttendanceRecord.fromJson(e as Map<String, dynamic>))
          .toList();
      return ChildAttendance(summary: summary, records: records);
    } catch (e) {
      throw toApi(e);
    }
  }
}

final childAttendanceProvider =
    FutureProvider.autoDispose.family<ChildAttendance, int>((ref, id) {
  return ref.watch(attendanceRepositoryProvider).forChild(id);
});

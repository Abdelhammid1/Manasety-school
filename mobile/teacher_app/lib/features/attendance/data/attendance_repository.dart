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

  Future<Map<int, AttendanceMark>> fetchExisting(int sectionId, DateTime date) async {
    try {
      final r = await _dio.get(
        Endpoints.teacherAttendance,
        queryParameters: {
          'section_id': sectionId,
          'date': _fmt(date),
        },
      );
      final rows = (r.data['records'] as List?) ?? const [];
      final out = <int, AttendanceMark>{};
      for (final row in rows) {
        final m = row as Map<String, dynamic>;
        final st = attendanceFromWire(m['status'] as String?);
        out[m['enrollment_id'] as int] = AttendanceMark(
          status: st,
          notes: m['notes'] as String?,
        );
      }
      return out;
    } catch (e) {
      throw toApi(e);
    }
  }

  /// Returns { creates, updates, absent_notifications }.
  Future<Map<String, int>> saveBulk({
    required int sectionId,
    required DateTime date,
    required Map<int, AttendanceMark> marks,
  }) async {
    try {
      final records = <Map<String, dynamic>>[];
      for (final entry in marks.entries) {
        final st = entry.value.status;
        if (st == null) continue; // skip unmarked
        records.add({
          'enrollment_id': entry.key,
          'status': st.wire,
          if (entry.value.notes != null && entry.value.notes!.isNotEmpty)
            'notes': entry.value.notes,
        });
      }
      final r = await _dio.post(Endpoints.teacherAttendance, data: {
        'section_id': sectionId,
        'date': _fmt(date),
        'records': records,
      });
      return {
        'creates': (r.data['creates'] as int?) ?? 0,
        'updates': (r.data['updates'] as int?) ?? 0,
        'absent_notifications': (r.data['absent_notifications'] as int?) ?? 0,
      };
    } catch (e) {
      throw toApi(e);
    }
  }

  String _fmt(DateTime d) =>
      '${d.year.toString().padLeft(4, "0")}-${d.month.toString().padLeft(2, "0")}-${d.day.toString().padLeft(2, "0")}';
}

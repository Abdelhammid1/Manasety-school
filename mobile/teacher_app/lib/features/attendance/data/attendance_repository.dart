import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class TeacherStudent {
  final int enrollmentId, studentId;
  final String? permanentCode, fullName;
  const TeacherStudent({required this.enrollmentId, required this.studentId,
    this.permanentCode, this.fullName});
  factory TeacherStudent.fromJson(Map<String, dynamic> j) => TeacherStudent(
    enrollmentId: (j['enrollment_id'] as num).toInt(),
    studentId: (j['student_id'] as num).toInt(),
    permanentCode: j['permanent_code'] as String?,
    fullName: j['full_name'] as String?,
  );
}

class AttendanceRecord {
  final int enrollmentId;
  final String status; // present, absent, late
  final String? notes;
  const AttendanceRecord({required this.enrollmentId, required this.status, this.notes});
  factory AttendanceRecord.fromJson(Map<String, dynamic> j) => AttendanceRecord(
    enrollmentId: (j['enrollment_id'] as num).toInt(),
    status: j['status'] as String? ?? 'present',
    notes: j['notes'] as String?,
  );
  Map<String, dynamic> toJson() => {
    'enrollment_id': enrollmentId, 'status': status,
    if (notes != null) 'notes': notes,
  };
}

class ExistingAttendance {
  final String date;
  final List<AttendanceRecord> records;
  const ExistingAttendance({required this.date, required this.records});
  factory ExistingAttendance.fromJson(Map<String, dynamic> j) => ExistingAttendance(
    date: j['date'] as String? ?? '',
    records: ((j['records'] as List?) ?? [])
      .map((e) => AttendanceRecord.fromJson((e as Map).cast<String, dynamic>())).toList(),
  );
}

class AttendanceRepository {
  AttendanceRepository(this._dio);
  final Dio _dio;

  Future<List<TeacherStudent>> students(int sectionId) async {
    final r = await _dio.get(Endpoints.students, queryParameters: {'section_id': sectionId});
    return ((r.data as Map)['students'] as List)
      .map((e) => TeacherStudent.fromJson((e as Map).cast<String, dynamic>())).toList();
  }

  Future<ExistingAttendance> existing(int sectionId, {String? date}) async {
    final r = await _dio.get(Endpoints.attendanceExisting,
      queryParameters: {'section_id': sectionId, if (date != null) 'date': date});
    return ExistingAttendance.fromJson((r.data as Map).cast<String, dynamic>());
  }

  Future<Map<String, dynamic>> mark(int sectionId, String date,
      List<AttendanceRecord> records) async {
    final r = await _dio.post(Endpoints.attendanceMark, data: {
      'section_id': sectionId, 'date': date,
      'records': records.map((e) => e.toJson()).toList(),
    });
    return (r.data as Map).cast<String, dynamic>();
  }
}

final attendanceRepositoryProvider = Provider<AttendanceRepository>((ref) =>
    AttendanceRepository(ref.watch(dioProvider)));

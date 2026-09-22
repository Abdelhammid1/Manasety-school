import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';

class PickupCallDto {
  final int id;
  final int studentId;
  final String studentName;
  final String? gate;
  final int waitedMin;
  final bool seenByTeacher;
  final bool seenByStudent;

  const PickupCallDto({
    required this.id,
    required this.studentId,
    required this.studentName,
    required this.gate,
    required this.waitedMin,
    required this.seenByTeacher,
    required this.seenByStudent,
  });

  factory PickupCallDto.fromJson(Map<String, dynamic> j) => PickupCallDto(
        id: j['id'] as int,
        studentId: (j['student_id'] as int?) ?? 0,
        studentName: (j['student_name'] as String?) ?? '',
        gate: j['gate'] as String?,
        waitedMin: (j['waited_min'] as int?) ?? 0,
        seenByTeacher: (j['seen_by_teacher'] as bool?) ?? false,
        seenByStudent: (j['seen_by_student'] as bool?) ?? false,
      );
}

/// Simple, injection-friendly repository for the parent pickup calls.
class PickupRepository {
  PickupRepository(this._dio);
  final Dio _dio;

  Future<PickupCallDto> call({
    required int studentId,
    String? gate,
    String? note,
  }) async {
    final res = await _dio.post(
      Endpoints.parentPickupCall,
      data: {
        'student_id': studentId,
        if (gate != null) 'gate': gate,
        if (note != null) 'note': note,
      },
    );
    final j = res.data as Map<String, dynamic>;
    return PickupCallDto(
      id: j['call_id'] as int,
      studentId: j['student_id'] as int,
      studentName: '',
      gate: j['gate'] as String?,
      waitedMin: 0,
      seenByTeacher: false,
      seenByStudent: false,
    );
  }

  Future<List<PickupCallDto>> active() async {
    final res = await _dio.get(Endpoints.parentPickupActive);
    final list = (res.data['calls'] as List? ?? const []);
    return list
        .map((e) => PickupCallDto.fromJson(e as Map<String, dynamic>))
        .toList(growable: false);
  }

  Future<void> release(int callId) async {
    await _dio.post(Endpoints.parentPickupRelease(callId));
  }
}

final pickupRepositoryProvider = Provider<PickupRepository>((ref) {
  return PickupRepository(ref.watch(dioProvider));
});

final activePickupCallsProvider =
    FutureProvider.autoDispose<List<PickupCallDto>>((ref) async {
  final repo = ref.watch(pickupRepositoryProvider);
  return repo.active();
});

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../home/data/home_repository.dart';

class ProfileData {
  final String? fullName;
  final String? username;
  final String? role;
  final String? phone;
  final String? email;
  final String? classLabel;
  final String? permanentCode;
  final double? gpaPct;
  final double? attendancePct;

  const ProfileData({
    this.fullName, this.username, this.role, this.phone, this.email,
    this.classLabel, this.permanentCode, this.gpaPct, this.attendancePct,
  });
}

class ProfileRepository {
  ProfileRepository(this._dio);
  final Dio _dio;

  Future<ProfileData> fetch() async {
    // Combine /me (User) + /student/home (Student + stats).
    final me = await _dio.get(Endpoints.me);
    final u = (me.data['user'] as Map).cast<String, dynamic>();
    HomeData? home;
    try {
      final hr = await _dio.get(Endpoints.studentHome);
      home = HomeData.fromJson((hr.data as Map).cast<String, dynamic>());
    } catch (_) { /* student profile might not be linked */ }
    return ProfileData(
      fullName: (u['full_name'] ?? home?.student['full_name']) as String?,
      username: u['username'] as String?,
      role:     u['role_ar'] as String? ?? u['role'] as String?,
      phone:    u['phone']   as String?,
      email:    u['email']   as String?,
      classLabel:     home?.student['class'] as String?,
      permanentCode:  home?.student['permanent_code'] as String?,
      gpaPct:        home?.stats.gpaPct,
      attendancePct: home?.stats.attendancePct,
    );
  }
}

final profileRepositoryProvider = Provider<ProfileRepository>((ref) {
  return ProfileRepository(ref.watch(dioProvider));
});

final profileProvider = FutureProvider.autoDispose<ProfileData>((ref) {
  return ref.watch(profileRepositoryProvider).fetch();
});

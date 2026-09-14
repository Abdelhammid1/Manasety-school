import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/api/endpoints.dart';
import '../../../shared/models/user.dart';

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(ref.watch(dioProvider));
});

class AuthRepository {
  final Dio _dio;
  AuthRepository(this._dio);

  Future<({String token, AppUser user})> login(String username, String password) async {
    try {
      final r = await _dio.post(Endpoints.login, data: {
        'username': username,
        'password': password,
      });
      final token = r.data['token'] as String;
      final user = AppUser.fromJson(r.data['user'] as Map<String, dynamic>);
      return (token: token, user: user);
    } catch (e) {
      throw toApi(e);
    }
  }

  Future<AppUser> me() async {
    try {
      final r = await _dio.get(Endpoints.me);
      return AppUser.fromJson(r.data['user'] as Map<String, dynamic>);
    } catch (e) {
      throw toApi(e);
    }
  }
}

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

final secureStorageProvider = Provider<SecureStorage>((ref) => SecureStorage());

class SecureStorage {
  static const _tokenKey = 'manasety_teacher_jwt';
  static const _userKey = 'manasety_teacher_user_cache';

  final FlutterSecureStorage _storage = const FlutterSecureStorage(
    aOptions: AndroidOptions(encryptedSharedPreferences: true),
    iOptions: IOSOptions(accessibility: KeychainAccessibility.first_unlock),
  );

  Future<String?> readToken() => _storage.read(key: _tokenKey);
  Future<void> writeToken(String token) => _storage.write(key: _tokenKey, value: token);
  Future<void> deleteToken() => _storage.delete(key: _tokenKey);

  Future<String?> readUserJson() => _storage.read(key: _userKey);
  Future<void> writeUserJson(String json) => _storage.write(key: _userKey, value: json);
  Future<void> deleteUser() => _storage.delete(key: _userKey);

  Future<void> clearAll() async {
    await deleteToken();
    await deleteUser();
  }
}

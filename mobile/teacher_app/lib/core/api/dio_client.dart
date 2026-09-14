import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:pretty_dio_logger/pretty_dio_logger.dart';

import '../env.dart';
import '../storage/secure_storage.dart';
import 'package:manasety_ui/manasety_ui.dart';

/// المزوّد العام لـ Dio بعد ربط الـ interceptors.
final dioProvider = Provider<Dio>((ref) {
  final storage = ref.watch(secureStorageProvider);

  final dio = Dio(
    BaseOptions(
      baseUrl: Env.apiBase,
      connectTimeout: const Duration(seconds: 15),
      receiveTimeout: const Duration(seconds: 30),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
    ),
  );

  dio.interceptors.add(_AuthInterceptor(storage));
  dio.interceptors.add(_ErrorInterceptor());
  if (kDebugMode) {
    dio.interceptors.add(
      PrettyDioLogger(
        requestHeader: false,
        requestBody: true,
        responseBody: false,
        responseHeader: false,
        compact: true,
      ),
    );
  }
  return dio;
});

class _AuthInterceptor extends Interceptor {
  _AuthInterceptor(this._storage);
  final SecureStorage _storage;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    final token = await _storage.readToken();
    if (token != null && token.isNotEmpty) {
      options.headers['Authorization'] = 'Bearer $token';
    }
    handler.next(options);
  }
}

class _ErrorInterceptor extends Interceptor {
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    final mapped = _mapException(err);
    handler.reject(
      DioException(
        requestOptions: err.requestOptions,
        error: mapped,
        type: err.type,
        response: err.response,
      ),
    );
  }

  ApiException _mapException(DioException err) {
    if (err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.receiveTimeout ||
        err.type == DioExceptionType.sendTimeout ||
        err.type == DioExceptionType.connectionError) {
      return const NetworkException();
    }
    final status = err.response?.statusCode ?? 0;
    final body = err.response?.data;
    String? serverMsg;
    if (body is Map && body['error'] is String) {
      serverMsg = body['error'] as String;
    } else if (body is Map && body['message'] is String) {
      serverMsg = body['message'] as String;
    }
    if (status == 401) return UnauthorizedException(serverMsg ?? 'انتهت جلستك — يرجى إعادة تسجيل الدخول');
    if (status == 403) return ForbiddenException(serverMsg ?? 'لا تملك صلاحية');
    if (status == 404) return NotFoundException(serverMsg ?? 'غير موجود');
    if (status >= 400 && status < 500) return ValidationException(serverMsg ?? 'بيانات غير صحيحة');
    return ServerException(serverMsg ?? 'خلل في الخادم');
  }
}

/// أداة مساعدة لاستخراج ApiException من DioException بشكل آمن.
ApiException toApi(Object e) {
  if (e is ApiException) return e;
  if (e is DioException) {
    final inner = e.error;
    if (inner is ApiException) return inner;
  }
  return const ServerException();
}

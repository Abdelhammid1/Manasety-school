import 'dart:async';

import 'package:dio/dio.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:go_router/go_router.dart';

import '../api/endpoints.dart';
import 'local_notifications.dart';

/// Sprint 10 Phase 3 — Firebase Cloud Messaging integration.
///
/// Defensive: if Firebase config files (GoogleService-Info.plist /
/// google-services.json) are missing, everything no-ops so the app still
/// runs. The client can enable push simply by adding the config files.
class FcmService {
  final Dio _dio;
  final String appFlavor; // "teacher" or "parent"

  bool _initialized = false;
  String? _token;
  StreamSubscription<String>? _tokenSub;
  StreamSubscription<RemoteMessage>? _fgSub;
  StreamSubscription<RemoteMessage>? _openSub;
  static GoRouter? _router;

  FcmService(this._dio, {required this.appFlavor});

  /// Called by AuthController.signIn after a successful login.
  Future<void> init() async {
    if (_initialized) return;
    try {
      // Initialize Firebase — fails if google-services.json / GoogleService-Info.plist
      // is missing. In that case we silently no-op.
      await Firebase.initializeApp();
    } catch (e) {
      if (kDebugMode) {
        debugPrint('[fcm] Firebase.initializeApp failed (no config?): $e');
      }
      return;
    }

    await LocalNotifications.init();

    final messaging = FirebaseMessaging.instance;
    try {
      await messaging.requestPermission(
        alert: true, badge: true, sound: true,
      );
    } catch (e) {
      if (kDebugMode) debugPrint('[fcm] requestPermission failed: $e');
    }

    // Foreground handler: FCM does NOT show notifications while the app is
    // in the foreground, so we synthesize a local one.
    _fgSub = FirebaseMessaging.onMessage.listen((msg) async {
      final n = msg.notification;
      if (n != null) {
        await LocalNotifications.show(
          id: DateTime.now().millisecondsSinceEpoch ~/ 1000,
          title: n.title ?? '',
          body: n.body ?? '',
          payload: msg.data['route'] as String?,
        );
      }
    });

    // Tapped from background/quit
    _openSub = FirebaseMessaging.onMessageOpenedApp.listen(_handleOpened);
    // App was launched by tapping a notification while terminated
    final launched = await messaging.getInitialMessage();
    if (launched != null) _handleOpened(launched);

    // Register + send token
    try {
      _token = await messaging.getToken();
      if (_token != null) await _sendToken(_token!);
    } catch (e) {
      if (kDebugMode) debugPrint('[fcm] getToken failed: $e');
    }

    _tokenSub = messaging.onTokenRefresh.listen((t) async {
      _token = t;
      await _sendToken(t);
    });

    _initialized = true;
  }

  /// Called by AuthController.signOut. Deletes the token server-side + locally.
  Future<void> dispose() async {
    await _fgSub?.cancel();
    await _openSub?.cancel();
    await _tokenSub?.cancel();
    _fgSub = _openSub = _tokenSub = null;
    if (_token != null) {
      try {
        await _dio.delete(Endpoints.deviceToken, data: {'token': _token});
      } catch (_) {/* ignore */}
    }
    try {
      await FirebaseMessaging.instance.deleteToken();
    } catch (_) {/* ignore */}
    _token = null;
    _initialized = false;
  }

  Future<void> _sendToken(String token) async {
    try {
      await _dio.post(Endpoints.deviceToken, data: {
        'token': token,
        'platform': _platform(),
        'app': appFlavor,
      });
    } catch (e) {
      if (kDebugMode) debugPrint('[fcm] send device-token failed: $e');
    }
  }

  String _platform() {
    // firebase_messaging supports iOS + Android for this project
    if (defaultTargetPlatform == TargetPlatform.iOS) return 'ios';
    return 'android';
  }

  void _handleOpened(RemoteMessage msg) {
    final route = msg.data['route'] as String?;
    if (route == null || route.isEmpty) return;
    // Also mark the notification as read if we know its id
    final nid = msg.data['notification_id'];
    if (nid != null) {
      unawaited(_markRead(int.tryParse('$nid')));
    }
    _router?.go(route);
  }

  Future<void> _markRead(int? id) async {
    if (id == null) return;
    try {
      await _dio.post(Endpoints.notificationRead(id));
    } catch (_) {/* ignore */}
  }

  /// Should be called once from ManasetyApp after routerProvider is built,
  /// so deep-links from push taps can navigate.
  static void bindRouter(GoRouter router) => _router = router;
}

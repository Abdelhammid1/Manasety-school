import 'dart:convert';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api/dio_client.dart';
import '../../../core/env.dart';
import '../../../core/push/fcm_service.dart';
import '../../../core/storage/secure_storage.dart';
import '../../../shared/models/user.dart';
import '../data/auth_repository.dart';

sealed class AuthState {
  const AuthState();
}

class AuthBooting extends AuthState {
  const AuthBooting();
}

class Unauthenticated extends AuthState {
  final String? lastMessage;
  const Unauthenticated({this.lastMessage});
}

class Authenticated extends AuthState {
  final AppUser user;
  const Authenticated(this.user);
}

/// Sprint 10 Phase 3 — FCM service instance shared per app lifecycle.
final fcmServiceProvider = Provider<FcmService>((ref) {
  return FcmService(ref.watch(dioProvider), appFlavor: Env.appFlavor);
});

final authControllerProvider =
    NotifierProvider<AuthController, AuthState>(AuthController.new);

class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    _bootstrap();
    return const AuthBooting();
  }

  Future<void> _bootstrap() async {
    final storage = ref.read(secureStorageProvider);
    final token = await storage.readToken();
    if (token == null || token.isEmpty) {
      state = const Unauthenticated();
      return;
    }
    final cached = await storage.readUserJson();
    if (cached != null) {
      try {
        state = Authenticated(AppUser.fromJson(jsonDecode(cached)));
        _initFcmAsync();
      } catch (_) {
        state = const Unauthenticated();
      }
    } else {
      try {
        final user = await ref.read(authRepositoryProvider).me();
        await storage.writeUserJson(jsonEncode(user.toJson()));
        state = Authenticated(user);
        _initFcmAsync();
      } catch (_) {
        await storage.clearAll();
        state = const Unauthenticated();
      }
    }
  }

  Future<void> signIn(String username, String password) async {
    final storage = ref.read(secureStorageProvider);
    final result = await ref.read(authRepositoryProvider).login(username, password);
    await storage.writeToken(result.token);
    await storage.writeUserJson(jsonEncode(result.user.toJson()));
    state = Authenticated(result.user);
    _initFcmAsync();
  }

  Future<void> signOut({String? message}) async {
    // Unregister the FCM token BEFORE clearing the JWT, so the DELETE request
    // still authenticates.
    try {
      await ref.read(fcmServiceProvider).dispose();
    } catch (_) {/* ignore */}
    await ref.read(secureStorageProvider).clearAll();
    state = Unauthenticated(lastMessage: message);
  }

  /// Fire-and-forget FCM init after successful auth.
  void _initFcmAsync() {
    Future<void>(() async {
      try {
        await ref.read(fcmServiceProvider).init();
      } catch (_) {/* ignore — Firebase config likely missing in dev */}
    });
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:manasety_ui/manasety_ui.dart';

import 'core/push/fcm_service.dart';
import 'core/router/app_router.dart';

class ManasetyApp extends ConsumerWidget {
  const ManasetyApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    // Sprint 10 Phase 3 — deep-link tapped push notifications through the router
    FcmService.bindRouter(router);
    return MaterialApp.router(
      title: 'بوابة المعلم',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.light(),
      darkTheme: AppTheme.dark(),
      themeMode: ThemeMode.system,
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
      ],
      routerConfig: router,
      // Day 12 — cap text scale at 130% so fixed-height chips/pills/badges
      // stay legible for large-font users without RenderFlex overflows.
      builder: (context, child) => MediaQuery.withClampedTextScaling(
        minScaleFactor: 1.0,
        maxScaleFactor: 1.3,
        child: child!,
      ),
    );
  }
}

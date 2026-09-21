import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:manasety_ui/manasety_ui.dart';

import 'core/router/app_router.dart';

class StudentApp extends ConsumerWidget {
  const StudentApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(appRouterProvider);

    final light = ThemeData(
      useMaterial3: true,
      brightness: Brightness.light,
      scaffoldBackgroundColor: ManasetyBrand.surface,
      colorScheme: ColorScheme.fromSeed(
        seedColor: ManasetyBrand.navy,
        brightness: Brightness.light,
      ).copyWith(
        primary: ManasetyBrand.navy,
        secondary: ManasetyBrand.blue,
        tertiary: ManasetyBrand.cyan,
        surface: ManasetyBrand.surfaceContainerLowest,
        onSurface: ManasetyBrand.onSurface,
        error: ManasetyBrand.error,
      ),
      textTheme: GoogleFonts.cairoTextTheme(
        Theme.of(context).textTheme,
      ).apply(
        bodyColor: ManasetyBrand.onSurface,
        displayColor: ManasetyBrand.onSurface,
      ),
      extensions: const [ManasetyTokens.light],
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: true,
        foregroundColor: ManasetyBrand.onSurface,
      ),
    );

    return MaterialApp.router(
      title: 'منصتي - الطالب',
      debugShowCheckedModeBanner: false,
      theme: light,
      // Arabic RTL by default.
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar'), Locale('en')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      builder: (context, child) => Directionality(
        textDirection: TextDirection.rtl,
        child: child ?? const SizedBox.shrink(),
      ),
      routerConfig: router,
    );
  }
}

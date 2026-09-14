import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:manasety_ui/manasety_ui.dart';
import 'package:manasety_teacher/features/auth/presentation/login_screen.dart';

/// Smoke test: the login screen mounts and renders branded UI.
/// We test LoginScreen in isolation (not via the router) to avoid kicking off
/// real Dio fetches on screens further in the tree.
void main() {
  testWidgets('Login screen renders Arabic title and dخول button',
      (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        child: MaterialApp(
          theme: AppTheme.light(),
          locale: const Locale('ar'),
          supportedLocales: const [Locale('ar')],
          localizationsDelegates: const [
            GlobalMaterialLocalizations.delegate,
            GlobalCupertinoLocalizations.delegate,
            GlobalWidgetsLocalizations.delegate,
          ],
          home: const LoginScreen(),
        ),
      ),
    );
    await tester.pump();
    expect(find.text('بوابة المعلم'), findsOneWidget);
    expect(find.text('دخول'), findsOneWidget);
  });
}

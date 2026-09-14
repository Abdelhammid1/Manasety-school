import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:manasety_ui/manasety_ui.dart';
import 'package:manasety_parent/features/auth/presentation/login_screen.dart';

void main() {
  testWidgets('Login screen renders Arabic title and login button',
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
    expect(find.text('بوابة ولي الأمر'), findsOneWidget);
    expect(find.text('دخول'), findsOneWidget);
  });
}

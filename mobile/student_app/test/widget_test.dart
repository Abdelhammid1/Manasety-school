import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:manasety_student/app.dart';

void main() {
  testWidgets('boots to splash', (WidgetTester tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: StudentApp()),
    );
    await tester.pump();
    // The splash renders the "منصتي" wordmark.
    expect(find.text('منصتي'), findsOneWidget);
  });
}

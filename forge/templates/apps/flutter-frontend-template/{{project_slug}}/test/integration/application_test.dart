import 'package:material_ui/material_ui.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:{{project_slug}}/bootstrap.dart';

void main() {
  testWidgets('application composes storage, routing and theme', (tester) async {
    SharedPreferences.setMockInitialValues({});
    await bootstrap();
    await tester.pump();
    await tester.pump(const Duration(seconds: 1));
    expect(find.byType(MaterialApp), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

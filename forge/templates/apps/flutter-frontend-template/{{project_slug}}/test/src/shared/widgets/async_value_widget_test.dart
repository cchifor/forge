import 'package:flutter/material.dart';
import 'package:{{project_slug}}/src/shared/widgets/async_value_widget.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import '../../../helpers/test_helpers.dart';

void main() {
  group('AsyncValueWidget', () {
    testWidgets('shows loading indicator for AsyncLoading', (tester) async {
      await tester.pumpApp(
        AsyncValueWidget<String>(
          value: const AsyncLoading(),
          data: (data) => Text(data),
        ),
      );

      expect(find.byType(CircularProgressIndicator), findsOneWidget);
    });

    testWidgets('shows data widget for AsyncData', (tester) async {
      await tester.pumpApp(
        AsyncValueWidget<String>(
          value: const AsyncData('Hello'),
          data: (data) => Text(data),
        ),
      );

      expect(find.text('Hello'), findsOneWidget);
    });

    testWidgets('shows error widget for AsyncError', (tester) async {
      await tester.pumpApp(
        AsyncValueWidget<String>(
          value: AsyncError(Exception('test error'), StackTrace.current),
          data: (data) => Text(data),
        ),
      );

      expect(find.byIcon(Icons.error_outline), findsOneWidget);
    });

    testWidgets('shows custom loading widget', (tester) async {
      await tester.pumpApp(
        AsyncValueWidget<String>(
          value: const AsyncLoading(),
          data: (data) => Text(data),
          loading: () => const Text('Custom Loading'),
        ),
      );

      expect(find.text('Custom Loading'), findsOneWidget);
    });
  });
}

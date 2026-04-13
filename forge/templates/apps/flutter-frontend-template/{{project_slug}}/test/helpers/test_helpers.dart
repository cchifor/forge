import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

Widget createTestApp({
  required Widget child,
  List<Object> overrides = const [],
}) {
  return ProviderScope(
    overrides: overrides.cast(),
    child: MaterialApp(home: child),
  );
}

extension PumpApp on WidgetTester {
  Future<void> pumpApp(
    Widget widget, {
    List<Object> overrides = const [],
  }) async {
    await pumpWidget(
      createTestApp(
        child: widget,
        overrides: overrides,
      ),
    );
  }
}

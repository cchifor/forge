import 'package:flutter/material.dart' as legacy;
import 'package:flutter_test/flutter_test.dart';
import 'package:forge_canvas/forge_canvas.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:material_ui/material_ui.dart';

void main() {
  testWidgets('Markdown inherits the modern dark theme and legacy localizations',
      (tester) async {
    final theme = ThemeData.dark();
    await tester.pumpWidget(MaterialApp(
      theme: theme,
      home: const Scaffold(
        body: Report(markdown: '# A report\n\nA selectable paragraph.'),
      ),
    ));
    await tester.pumpAndSettle();

    final context = tester.element(find.byType(MarkdownBody));
    expect(legacy.Theme.of(context).brightness, Brightness.dark);
    expect(legacy.Theme.of(context).colorScheme.primary, theme.colorScheme.primary);
    expect(legacy.MaterialLocalizations.of(context).copyButtonLabel, isNotEmpty);
    expect(find.text('A report'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

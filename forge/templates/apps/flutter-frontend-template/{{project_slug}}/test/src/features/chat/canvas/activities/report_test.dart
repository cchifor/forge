import 'package:flutter/material.dart' as legacy;
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:{{project_slug}}/src/features/chat/canvas/activities/report.dart';
import 'package:{{project_slug}}/src/features/chat/domain/workspace_activity.dart';

void main() {
  testWidgets('report Markdown inherits the app dark theme and selection localizations', (
    tester,
  ) async {
    final theme = ThemeData.dark();
    await tester.pumpWidget(
      MaterialApp(
        theme: theme,
        home: const Scaffold(
          body: ReportActivity(
            activity: WorkspaceActivity(
              engine: AgentEngine.agUi,
              activityType: 'report',
              messageId: 'report-1',
              content: {
                'title': 'Report title',
                'markdown': '## Findings\n\nReport body',
              },
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    expect(find.text('Report title'), findsOneWidget);
    final markdown = tester.widget<MarkdownBody>(find.byType(MarkdownBody));
    expect(markdown.selectable, isTrue);
    final context = tester.element(find.byType(MarkdownBody));
    expect(legacy.Theme.of(context).brightness, Brightness.dark);
    expect(
      legacy.Theme.of(context).colorScheme.primary,
      theme.colorScheme.primary,
    );
    expect(
      legacy.MaterialLocalizations.of(context).copyButtonLabel,
      isNotEmpty,
    );
    expect(find.text('Report body'), findsOneWidget);
  });
}

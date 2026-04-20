import 'package:flutter/material.dart';
import 'package:flutter_highlight/flutter_highlight.dart';
import 'package:flutter_highlight/themes/github.dart';

/// CodeViewer canvas component — syntax-highlighted code with optional
/// filename header and line numbers.
///
/// Props schema:
/// forge/templates/_shared/canvas-components/CodeViewer.props.schema.json
class CodeViewer extends StatelessWidget {
  final String code;
  final String language;
  final String? filename;
  final bool showLineNumbers;

  const CodeViewer({
    super.key,
    required this.code,
    required this.language,
    this.filename,
    this.showLineNumbers = false,
  });

  factory CodeViewer.fromProps(Map<String, dynamic> props) => CodeViewer(
        code: (props['code'] as String?) ?? '',
        language: (props['language'] as String?) ?? 'plaintext',
        filename: props['filename'] as String?,
        showLineNumbers: (props['showLineNumbers'] as bool?) ?? false,
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final highlighted = HighlightView(
      code,
      language: language,
      theme: githubTheme,
      padding: const EdgeInsets.all(12),
      textStyle: const TextStyle(
        fontFamily: 'monospace',
        fontSize: 13,
        height: 1.5,
      ),
    );

    Widget body = highlighted;
    if (showLineNumbers) {
      final lineCount = code.split('\n').length;
      body = Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.end,
              children: List.generate(
                lineCount,
                (i) => Text(
                  '${i + 1}',
                  style: TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 13,
                    height: 1.5,
                    color: theme.colorScheme.outline,
                  ),
                ),
              ),
            ),
          ),
          Expanded(child: highlighted),
        ],
      );
    }

    return Card(
      clipBehavior: Clip.antiAlias,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (filename != null && filename!.isNotEmpty)
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
              decoration: BoxDecoration(
                color: theme.colorScheme.surfaceContainerHighest,
                border: Border(
                  bottom: BorderSide(color: theme.colorScheme.outlineVariant),
                ),
              ),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text(filename!, style: theme.textTheme.bodySmall),
                  Text(
                    language.toUpperCase(),
                    style: theme.textTheme.bodySmall?.copyWith(
                      letterSpacing: 1.5,
                      color: theme.colorScheme.outline,
                    ),
                  ),
                ],
              ),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: body,
          ),
        ],
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';

/// Report canvas component — renders a Markdown document with an
/// optional title header. Matches @forge/canvas-vue and canvas-svelte
/// visually via the ForgeTheme.
///
/// Props schema:
/// forge/templates/_shared/canvas-components/Report.props.schema.json
class Report extends StatelessWidget {
  final String? title;
  final String markdown;

  const Report({
    super.key,
    this.title,
    required this.markdown,
  });

  factory Report.fromProps(Map<String, dynamic> props) => Report(
        title: props['title'] as String?,
        markdown: (props['markdown'] as String?) ?? '',
      );

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Card(
      margin: const EdgeInsets.symmetric(vertical: 4, horizontal: 0),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (title != null && title!.isNotEmpty) ...[
              Text(
                title!,
                style: theme.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 12),
            ],
            MarkdownBody(
              data: markdown,
              selectable: true,
              styleSheet: MarkdownStyleSheet.fromTheme(theme).copyWith(
                codeblockDecoration: BoxDecoration(
                  color: theme.colorScheme.surfaceContainerHighest,
                  borderRadius: BorderRadius.circular(6),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

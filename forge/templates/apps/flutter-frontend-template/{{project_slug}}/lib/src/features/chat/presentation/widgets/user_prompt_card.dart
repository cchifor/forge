import 'package:flutter/material.dart';

import '../../domain/user_prompt_payload.dart';

class UserPromptCard extends StatelessWidget {
  const UserPromptCard({
    super.key,
    required this.prompt,
    required this.onRespond,
  });

  final UserPromptPayload prompt;
  final void Function(String answer) onRespond;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      key: const ValueKey('user-prompt-card'),
      color: scheme.tertiaryContainer.withValues(alpha: 0.4),
      shape: RoundedRectangleBorder(
        side: BorderSide(color: scheme.tertiary.withValues(alpha: 0.5)),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              prompt.question,
              style: Theme.of(context)
                  .textTheme
                  .bodyMedium
                  ?.copyWith(fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: prompt.options.map((opt) {
                final isRecommended =
                    opt.recommended != null && opt.recommended!.isNotEmpty;
                return FilledButton.tonal(
                  onPressed: () => onRespond(opt.label),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(opt.label),
                      if (isRecommended) ...[
                        const SizedBox(width: 6),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 1,
                          ),
                          decoration: BoxDecoration(
                            color: scheme.primary.withValues(alpha: 0.15),
                            borderRadius: BorderRadius.circular(4),
                          ),
                          child: Text(
                            'recommended',
                            style: TextStyle(
                              fontSize: 9,
                              color: scheme.primary,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ],
                    ],
                  ),
                );
              }).toList(),
            ),
          ],
        ),
      ),
    );
  }
}

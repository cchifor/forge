import 'package:flutter/material.dart';

import '../../theme/design_tokens.dart';
import '../../core/errors/error_formatters.dart';

class ErrorDisplayWidget extends StatelessWidget {
  const ErrorDisplayWidget({
    required this.error,
    this.onRetry,
    super.key,
  });

  final Object error;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.p24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.error_outline,
              size: DesignTokens.iconXL,
              color: theme.colorScheme.error,
            ),
            const SizedBox(height: DesignTokens.p16),
            Text(
              formatException(error),
              textAlign: TextAlign.center,
              style: theme.textTheme.bodyLarge,
            ),
            if (onRetry != null) ...[
              const SizedBox(height: DesignTokens.p16),
              FilledButton.tonalIcon(
                onPressed: onRetry,
                icon: const Icon(Icons.refresh),
                label: const Text('Retry'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

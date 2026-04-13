import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../../theme/design_tokens.dart';
import '../../../shared/feedback/feedback_extensions.dart';
import '../../../theme/layout_theme_extension.dart';
import 'auth_controller.dart';

class LoginPage extends ConsumerWidget {
  const LoginPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);
    final theme = Theme.of(context);

    ref.listen(authControllerProvider, (prev, next) {
      handleAsyncFeedback(context, prev, next);
    });

    final layoutExt = theme.extension<LayoutThemeExtension>()!;

    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: layoutExt.loginCardMaxWidth),
          child: Card(
            margin: const EdgeInsets.all(DesignTokens.p24),
            child: Padding(
              padding: const EdgeInsets.all(DesignTokens.p32),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(
                    Icons.flutter_dash,
                    size: DesignTokens.iconHero,
                    color: theme.colorScheme.primary,
                  ),
                  const SizedBox(height: DesignTokens.p24),
                  Text(
                    'Welcome',
                    style: theme.textTheme.headlineMedium?.copyWith(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: DesignTokens.p8),
                  Text(
                    'Sign in to continue',
                    style: theme.textTheme.bodyLarge?.copyWith(
                      color: theme.colorScheme.onSurfaceVariant,
                    ),
                  ),
                  const SizedBox(height: DesignTokens.p32),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: authState.isLoading
                          ? null
                          : () {
                              if (kIsWeb) {
                                // On web, redirect to Gatekeeper login endpoint
                                launchUrl(
                                  Uri.parse('/auth/login?redirect_uri=${Uri.encodeComponent('/')}'),
                                  webOnlyWindowName: '_self',
                                );
                              } else {
                                ref
                                    .read(authControllerProvider.notifier)
                                    .login();
                              }
                            },
                      icon: authState.isLoading
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                              ),
                            )
                          : const Icon(Icons.login),
                      label: Text(
                        authState.isLoading ? 'Signing in...' : 'Sign In',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

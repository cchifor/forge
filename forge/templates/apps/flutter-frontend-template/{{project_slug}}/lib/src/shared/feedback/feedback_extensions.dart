import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/error_formatters.dart';

/// Mixin-style helper for showing feedback from [AsyncValue] provider changes.
///
/// Usage in a [ConsumerWidget.build] or [ConsumerState.build]:
/// ```dart
/// showFeedbackOnChange(
///   ref: ref,
///   context: context,
///   value: ref.watch(itemsControllerProvider),
///   successMessage: 'Item created',
/// );
/// ```
void showFeedbackOnChange({
  required WidgetRef ref,
  required BuildContext context,
  required AsyncValue<void> value,
  AsyncValue<void>? previous,
  String? successMessage,
}) {
  // This is called during build -- the ref.listen approach is not usable
  // without the provider type. Instead, pages use this as a manual check.
}

/// Extension on [WidgetRef] for one-liner async feedback via [ref.listen].
///
/// Because Riverpod 3.x doesn't export [ProviderListenable], this extension
/// provides a callback-based approach: the caller passes the listen call result.
extension FeedbackSnackBarX on BuildContext {
  /// Show an error SnackBar.
  void showErrorSnackBar(Object error) {
    ScaffoldMessenger.of(this)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          content: Text(formatException(error)),
          behavior: SnackBarBehavior.floating,
          backgroundColor: Theme.of(this).colorScheme.error,
          showCloseIcon: true,
          closeIconColor: Theme.of(this).colorScheme.onError,
          duration: const Duration(seconds: 6),
        ),
      );
  }

  /// Show an info SnackBar.
  void showInfoSnackBar(String message) {
    ScaffoldMessenger.of(this)
      ..clearSnackBars()
      ..showSnackBar(
        SnackBar(
          content: Text(message),
          behavior: SnackBarBehavior.floating,
          duration: const Duration(seconds: 4),
        ),
      );
  }
}

/// Helper to use inside [ref.listen] callbacks for [AsyncValue] providers.
///
/// Usage:
/// ```dart
/// ref.listen(myProvider, (prev, next) {
///   handleAsyncFeedback(context, prev, next, successMessage: 'Done!');
/// });
/// ```
void handleAsyncFeedback<T>(
  BuildContext context,
  AsyncValue<T>? previous,
  AsyncValue<T> next, {
  String? successMessage,
}) {
  // Error
  if (next.hasError && !next.isLoading) {
    context.showErrorSnackBar(next.error!);
  }

  // Success
  if (successMessage != null &&
      previous != null &&
      previous.isLoading &&
      next.hasValue &&
      !next.isLoading) {
    context.showInfoSnackBar(successMessage);
  }
}

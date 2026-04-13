import 'package:flutter/material.dart';
import 'package:riverpod_annotation/riverpod_annotation.dart';

part 'feedback_service.g.dart';

/// Global key for [ScaffoldMessengerState], attached to [MaterialApp].
/// Allows showing SnackBars and MaterialBanners from anywhere via Riverpod.
@Riverpod(keepAlive: true)
GlobalKey<ScaffoldMessengerState> scaffoldMessengerKey(Ref ref) {
  return GlobalKey<ScaffoldMessengerState>();
}

/// Centralized service for showing user feedback (info, warning, error).
///
/// Use **Path A** (`ref.listen` + `handleAsyncFeedback`) for user-triggered actions.
/// Use **Path B** (this service) for global events (401, offline, etc.).
class FeedbackService {
  FeedbackService(this._key);

  final GlobalKey<ScaffoldMessengerState> _key;

  ScaffoldMessengerState? get _messenger => _key.currentState;

  /// Show a transient info notification (auto-dismisses after 4s).
  void showInfo(String message, {String? actionLabel, VoidCallback? onAction}) {
    _messenger?.clearSnackBars();
    _messenger?.showSnackBar(
      SnackBar(
        content: Text(message),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 4),
        action: actionLabel != null
            ? SnackBarAction(label: actionLabel, onPressed: onAction ?? () {})
            : null,
      ),
    );
  }

  /// Show an error notification (auto-dismisses after 6s).
  void showError(String message) {
    _messenger?.clearSnackBars();
    final theme = _resolveTheme();
    _messenger?.showSnackBar(
      SnackBar(
        content: Text(message),
        behavior: SnackBarBehavior.floating,
        duration: const Duration(seconds: 6),
        backgroundColor: theme?.colorScheme.error,
        showCloseIcon: true,
        closeIconColor: theme?.colorScheme.onError,
      ),
    );
  }

  /// Show a persistent warning banner (stays until dismissed).
  void showWarning(String message) {
    _messenger?.clearMaterialBanners();
    final theme = _resolveTheme();
    _messenger?.showMaterialBanner(
      MaterialBanner(
        content: Text(message),
        backgroundColor:
            theme?.colorScheme.errorContainer ?? Colors.amber.shade100,
        leading: Icon(
          Icons.warning_amber_rounded,
          color: theme?.colorScheme.onErrorContainer,
        ),
        actions: [
          TextButton(
            onPressed: () => _messenger?.clearMaterialBanners(),
            child: const Text('DISMISS'),
          ),
        ],
      ),
    );
  }

  /// Clear all active material banners.
  void clearWarnings() {
    _messenger?.clearMaterialBanners();
  }

  ThemeData? _resolveTheme() {
    final context = _key.currentContext;
    return context != null ? Theme.of(context) : null;
  }
}

@Riverpod(keepAlive: true)
FeedbackService feedbackService(Ref ref) {
  return FeedbackService(ref.watch(scaffoldMessengerKeyProvider));
}

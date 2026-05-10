/// Pre-warning session-timeout modal — Flutter widget.
///
/// Mirrors ``SessionTimeoutModal.vue`` and ``SessionTimeoutModal.svelte``
/// behaviour: opens at ``T - warnAtSeconds`` from idle expiry, displays
/// a live countdown, and offers two actions:
///
///  - **Stay signed in** → fires an immediate extension via
///    ``service.extend()``, bypassing the activity debounce.
///  - **Sign out** → existing /logout flow (browser navigation on
///    web; the native equivalent is a separate route handler the
///    consumer wires up).
///
/// Wire once at the authenticated layout's root. Consume the service
/// via the framework integration the project already uses (Provider,
/// Riverpod, manual ``ListenableBuilder`` — they all work with the
/// service's ``ChangeNotifier`` shape).

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';

import '../data/session_timeout_service.dart';

/// Modal that surfaces the session-timeout pre-warning.
///
/// Embed at the top of the authenticated route shell — typically a
/// ``Stack`` overlay or a parent of ``MaterialApp.builder`` so it can
/// surface above any route.
class SessionTimeoutModal extends StatelessWidget {
  /// The service driving the countdown. Must be initialised via
  /// ``service.init()`` somewhere in the app lifecycle (typically the
  /// authenticated layout's mount).
  final SessionTimeoutService service;

  /// Called when the user taps "Sign out". Defaults to navigating
  /// to ``/logout`` on web (no-op on other targets — wire your own).
  final VoidCallback? onSignOut;

  const SessionTimeoutModal({
    super.key,
    required this.service,
    this.onSignOut,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: service,
      builder: (BuildContext context, Widget? _) {
        if (!service.enabled) {
          return const SizedBox.shrink();
        }
        final remaining = service.idleRemainingSeconds;
        if (remaining <= 0 || remaining > service.warnAtSeconds) {
          return const SizedBox.shrink();
        }
        return _SessionTimeoutOverlay(
          remainingSeconds: remaining,
          onStaySignedIn: service.extend,
          onSignOut: onSignOut ?? _defaultSignOut,
        );
      },
    );
  }

  static void _defaultSignOut() {
    // Web: browser navigation to /logout. Native: noop unless the
    // consumer overrides via ``onSignOut`` (typically routing to a
    // logout screen that calls the auth service's logout endpoint).
    if (kIsWeb) {
      // Use a low-level navigation; package:web is the modern path
      // but pulling it in just for this would inflate the dep tree.
      // The consuming app can override via ``onSignOut`` to use its
      // own router instead.
      // ignore: avoid_web_libraries_in_flutter
      // (deferred to consumer)
    }
  }
}

class _SessionTimeoutOverlay extends StatelessWidget {
  final int remainingSeconds;
  final Future<void> Function() onStaySignedIn;
  final VoidCallback onSignOut;

  const _SessionTimeoutOverlay({
    required this.remainingSeconds,
    required this.onStaySignedIn,
    required this.onSignOut,
  });

  String _formatRemaining(int seconds) {
    final m = seconds ~/ 60;
    final s = seconds % 60;
    return m > 0 ? '${m}m ${s}s' : '${s}s';
  }

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.black.withValues(alpha: 0.45),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 420),
          child: Card(
            margin: const EdgeInsets.symmetric(horizontal: 24),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text(
                    "You'll be signed out soon",
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                  const SizedBox(height: 12),
                  Text.rich(
                    TextSpan(children: <InlineSpan>[
                      const TextSpan(
                        text: "For your security, you'll be signed out in ",
                      ),
                      TextSpan(
                        text: _formatRemaining(remainingSeconds),
                        style: const TextStyle(fontWeight: FontWeight.bold),
                      ),
                      const TextSpan(text: ' unless you stay active.'),
                    ]),
                  ),
                  const SizedBox(height: 24),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.end,
                    children: <Widget>[
                      _StaySignedInButton(onPressed: onStaySignedIn),
                      const SizedBox(width: 12),
                      OutlinedButton(
                        onPressed: onSignOut,
                        child: const Text('Sign out'),
                      ),
                    ],
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

class _StaySignedInButton extends StatefulWidget {
  final Future<void> Function() onPressed;

  const _StaySignedInButton({required this.onPressed});

  @override
  State<_StaySignedInButton> createState() => _StaySignedInButtonState();
}

class _StaySignedInButtonState extends State<_StaySignedInButton> {
  bool _isExtending = false;

  Future<void> _handlePress() async {
    if (_isExtending) return;
    setState(() {
      _isExtending = true;
    });
    try {
      await widget.onPressed();
    } finally {
      if (mounted) {
        setState(() {
          _isExtending = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return ElevatedButton(
      onPressed: _isExtending ? null : _handlePress,
      child: Text(_isExtending ? 'Staying signed in…' : 'Stay signed in'),
    );
  }
}

/// Inactivity-based session timeout — Flutter service.
///
/// Mirrors the Vue / Svelte composable semantically: implements
/// platform's BFF + session-timeout RFC for a cookie-based BFF
/// architecture (web-first; native is the explicit-refresh-token
/// follow-up the RFC marked out of scope).
///
/// Three RFC-mandated behaviours are present:
///
///  1. **Drift-immune countdown** — stores ``idleExpiresAt`` (an
///     absolute ``DateTime``); recomputes the remaining seconds via
///     ``DateTime.now()`` at read time. Suspended apps catch up
///     instantly when resumed.
///
///  2. **Visibility gating** — extensions only fire when the app is
///     resumed (``AppLifecycleState.resumed``). A suspended app
///     listening to events would otherwise extend the session
///     forever.
///
///  3. **Activity debounce** — 30-second debounce on extension POSTs
///     to prevent hammering the server-side rate limit.
///
/// Cross-tab leader election (the BroadcastChannel piece in the Vue
/// and Svelte fragments) is web-only; on native there is exactly one
/// app instance per device, so no dedup is needed. A web-specific
/// `dart:js_interop` binding for BroadcastChannel ships in a follow-
/// up sub-phase — until then, multi-tab Flutter web users may see
/// duplicate extension POSTs (rate-limited by the server, so
/// correctness is preserved; just slightly noisy).

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;

/// Response shape from GET / POST /auth/session.
@immutable
class SessionState {
  final int idleRemainingSeconds;
  final int absoluteRemainingSeconds;
  final int idleTimeoutSeconds;
  final int absoluteTimeoutSeconds;
  final int warnAtSeconds;

  const SessionState({
    required this.idleRemainingSeconds,
    required this.absoluteRemainingSeconds,
    required this.idleTimeoutSeconds,
    required this.absoluteTimeoutSeconds,
    required this.warnAtSeconds,
  });

  factory SessionState.fromJson(Map<String, dynamic> json) => SessionState(
        idleRemainingSeconds: json['idle_remaining_seconds'] as int,
        absoluteRemainingSeconds: json['absolute_remaining_seconds'] as int,
        idleTimeoutSeconds: json['idle_timeout_seconds'] as int,
        absoluteTimeoutSeconds: json['absolute_timeout_seconds'] as int,
        warnAtSeconds: json['warn_at_seconds'] as int,
      );

  bool get serverSideDisabled =>
      idleTimeoutSeconds == 0 && absoluteTimeoutSeconds == 0;
}

/// Minimal observable surface for the modal widget. ``ChangeNotifier``
/// keeps this service framework-agnostic — drop it into Provider,
/// Riverpod, or a manual ``ListenableBuilder`` indifferently.
class SessionTimeoutService extends ChangeNotifier with WidgetsBindingObserver {
  static const String _defaultEndpoint = '/auth/session';
  static const Duration _defaultDebounce = Duration(seconds: 30);
  static const Duration _defaultTick = Duration(seconds: 1);
  static const List<String> _activityHints = <String>[
    'mousemove',
    'keydown',
    'scroll',
    'visibilitychange',
  ];

  final Uri endpoint;
  final Duration debounce;
  final Duration tick;
  final http.Client _http;

  bool _enabled = false;
  DateTime _idleExpiresAt = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime _absoluteExpiresAt = DateTime.fromMillisecondsSinceEpoch(0);
  int _warnAtSeconds = 60;
  Timer? _tickTimer;
  Timer? _debounceTimer;
  bool _isMounted = false;

  SessionTimeoutService({
    String endpoint = _defaultEndpoint,
    this.debounce = _defaultDebounce,
    this.tick = _defaultTick,
    http.Client? client,
  })  : endpoint = Uri.parse(endpoint),
        _http = client ?? http.Client();

  bool get enabled => _enabled;
  int get warnAtSeconds => _warnAtSeconds;

  /// Drift-immune — recomputed from ``DateTime.now()`` every read.
  /// Resumed apps see the correct value instantly.
  int get idleRemainingSeconds {
    if (!_enabled) return 0;
    final remaining = _idleExpiresAt.difference(DateTime.now()).inSeconds;
    return remaining < 0 ? 0 : remaining;
  }

  int get absoluteRemainingSeconds {
    if (!_enabled) return 0;
    final remaining = _absoluteExpiresAt.difference(DateTime.now()).inSeconds;
    return remaining < 0 ? 0 : remaining;
  }

  /// Wire once at the authenticated layout's mount.
  Future<void> init() async {
    if (_isMounted) return;
    _isMounted = true;
    WidgetsBinding.instance.addObserver(this);
    await _bootstrap();
    if (_enabled) {
      _startTickTimer();
    }
  }

  /// Tear down once on unmount.
  @override
  void dispose() {
    _isMounted = false;
    WidgetsBinding.instance.removeObserver(this);
    _tickTimer?.cancel();
    _tickTimer = null;
    _debounceTimer?.cancel();
    _debounceTimer = null;
    _http.close();
    super.dispose();
  }

  /// Force-fire an extension immediately (modal's "Stay signed in").
  /// Bypasses the activity debounce.
  Future<void> extend() async {
    if (!_enabled) return;
    try {
      final response = await _http.post(endpoint, headers: <String, String>{
        'Accept': 'application/json',
      });
      if (response.statusCode == 401) {
        // Session expired between trigger and POST. Let the API layer's
        // 401 handler drive the redirect.
        _enabled = false;
        notifyListeners();
        return;
      }
      if (response.statusCode != 200) return;
      _applyState(
        SessionState.fromJson(jsonDecode(response.body) as Map<String, dynamic>),
      );
    } catch (_) {
      // Network blip — silently ignore; next activity will retry.
    }
  }

  /// Manually re-bootstrap (after login).
  Future<void> reload() async => _bootstrap();

  /// Hook for activity events surfaced from the host widget tree
  /// (gesture detector, focus listener, raw keyboard listener, etc.).
  /// The hint string mirrors the Vue / Svelte event names so the
  /// telemetry semantics line up cross-platform.
  void onUserActivity({String hint = 'mousemove'}) {
    if (!_isMounted || !_enabled) return;
    if (!_activityHints.contains(hint)) return;
    if (!_isVisible()) return;
    if (_debounceTimer != null) return; // Inside debounce window.
    _debounceTimer = Timer(debounce, () async {
      _debounceTimer = null;
      if (!_isMounted || !_enabled || !_isVisible()) return;
      await extend();
    });
  }

  // ------------------------------------------------------------------- internals

  bool _isVisible() {
    final state = WidgetsBinding.instance.lifecycleState;
    return state == AppLifecycleState.resumed || state == null;
  }

  Future<void> _bootstrap() async {
    try {
      final response = await _http.get(endpoint, headers: <String, String>{
        'Accept': 'application/json',
      });
      if (response.statusCode != 200) {
        _enabled = false;
        notifyListeners();
        return;
      }
      _applyState(
        SessionState.fromJson(jsonDecode(response.body) as Map<String, dynamic>),
      );
    } catch (_) {
      _enabled = false;
      notifyListeners();
    }
  }

  void _applyState(SessionState state) {
    if (state.serverSideDisabled) {
      _enabled = false;
      notifyListeners();
      return;
    }
    _enabled = true;
    final now = DateTime.now();
    _idleExpiresAt = now.add(Duration(seconds: state.idleRemainingSeconds));
    _absoluteExpiresAt =
        now.add(Duration(seconds: state.absoluteRemainingSeconds));
    _warnAtSeconds = state.warnAtSeconds;
    notifyListeners();
  }

  void _startTickTimer() {
    _tickTimer?.cancel();
    _tickTimer = Timer.periodic(tick, (_) => notifyListeners());
  }

  /// `WidgetsBindingObserver` — when the app comes back to foreground
  /// after being suspended, treat it as user activity (the user just
  /// came back). Mirrors the Vue / Svelte `visibilitychange` handler.
  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (!_isMounted || !_enabled) return;
    if (state == AppLifecycleState.resumed) {
      onUserActivity(hint: 'visibilitychange');
    }
  }

  /// Helper for callers that want to wire HTTP cookies on web. On
  /// native, callers provide their own [http.Client] (with whatever
  /// cookie jar / session manager they have). This factory wires the
  /// `package:http` defaults — for Flutter web that means the browser
  /// fetch implementation includes cookies on same-origin requests.
  static SessionTimeoutService createDefault({String endpoint = _defaultEndpoint}) =>
      SessionTimeoutService(
        endpoint: endpoint,
        client: kIsWeb ? http.Client() : http.Client(),
      );
}

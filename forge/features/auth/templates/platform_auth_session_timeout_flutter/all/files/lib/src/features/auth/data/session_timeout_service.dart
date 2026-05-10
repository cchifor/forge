/// Inactivity-based session timeout — Flutter service.
///
/// Mirrors the Vue / Svelte composable semantically. Two modes:
///
///  - **web** — cookie-based BFF (Gatekeeper). `_extend()` POSTs to
///    `/auth/session`; the server is the source of truth for
///    countdown values. `bootstrap()` GETs the same endpoint.
///
///  - **native** — explicit refresh-token model (iOS / Android). The
///    Gatekeeper `/auth/session` endpoint is cookie-only, so native
///    bypasses it entirely. `_extend()` rotates the access token
///    via the consumer-supplied `refreshAccessToken` callback (wired
///    to `KeycloakAuthService.refreshAccessToken` in the host app).
///    Countdown is computed locally — `idle_remaining_seconds` is
///    capped at the configured idle timeout, so a long-lived access
///    token (e.g. 5 min) doesn't bypass the 30-min idle window the
///    compliance posture mandates.
///
/// Three RFC-mandated behaviours are present in both modes:
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
///  3. **Activity debounce** — 30-second debounce on extension calls
///     to avoid hammering the server-side rate limit (web) or
///     spamming the IdP refresh endpoint (native).
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

/// How the service obtains and refreshes the session.
enum SessionTimeoutMode { web, native }

/// Callback the service uses on native to rotate the access token.
///
/// Wire to ``AuthRepository.refreshAccessToken`` (which delegates to
/// ``KeycloakAuthService.refreshAccessToken`` under the hood). Returns
/// the new access token's expiry timestamp on success; throws when
/// the refresh token is rejected (revoked / expired).
typedef RefreshAccessToken = Future<DateTime?> Function();

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
  static const int _defaultIdleTimeoutSeconds = 1800; // 30 min
  static const int _defaultAbsoluteTimeoutSeconds = 43200; // 12 h
  static const int _defaultWarnAtSeconds = 60;
  static const List<String> _activityHints = <String>[
    'mousemove',
    'keydown',
    'scroll',
    'visibilitychange',
  ];

  final SessionTimeoutMode mode;
  final Uri endpoint;
  final Duration debounce;
  final Duration tick;
  final http.Client _http;
  final RefreshAccessToken? _refreshAccessToken;
  final int _nativeIdleTimeoutSeconds;
  final int _nativeAbsoluteTimeoutSeconds;
  final int _nativeWarnAtSeconds;
  final VoidCallback? _onForcedLogout;

  bool _enabled = false;
  DateTime _idleExpiresAt = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime _absoluteExpiresAt = DateTime.fromMillisecondsSinceEpoch(0);
  int _warnAtSeconds = _defaultWarnAtSeconds;
  Timer? _tickTimer;
  Timer? _debounceTimer;
  bool _isMounted = false;

  /// Web (default) — POSTs to /auth/session against the BFF.
  SessionTimeoutService({
    String endpoint = _defaultEndpoint,
    this.debounce = _defaultDebounce,
    this.tick = _defaultTick,
    http.Client? client,
  })  : mode = SessionTimeoutMode.web,
        endpoint = Uri.parse(endpoint),
        _http = client ?? http.Client(),
        _refreshAccessToken = null,
        _nativeIdleTimeoutSeconds = _defaultIdleTimeoutSeconds,
        _nativeAbsoluteTimeoutSeconds = _defaultAbsoluteTimeoutSeconds,
        _nativeWarnAtSeconds = _defaultWarnAtSeconds,
        _onForcedLogout = null;

  /// Native — uses [refreshAccessToken] to rotate the access token
  /// on activity; computes countdown locally.
  ///
  /// [idleTimeoutSeconds] / [absoluteTimeoutSeconds] / [warnAtSeconds]
  /// mirror the per-tenant defaults the Gatekeeper exposes on web
  /// (1800 / 43200 / 60). The native client doesn't ask the server
  /// for them; align with your deployment's `TenantConfig` defaults
  /// or pass overrides explicitly.
  ///
  /// [onForcedLogout] is called when the refresh-token rotation
  /// fails (revoked / expired) or the absolute timeout elapses.
  /// The host app typically wires this to `AuthRepository.logout()`
  /// + a navigation to the login route.
  SessionTimeoutService.forNative({
    required RefreshAccessToken refreshAccessToken,
    int idleTimeoutSeconds = _defaultIdleTimeoutSeconds,
    int absoluteTimeoutSeconds = _defaultAbsoluteTimeoutSeconds,
    int warnAtSeconds = _defaultWarnAtSeconds,
    VoidCallback? onForcedLogout,
    this.debounce = _defaultDebounce,
    this.tick = _defaultTick,
  })  : mode = SessionTimeoutMode.native,
        endpoint = Uri.parse(_defaultEndpoint),
        _http = http.Client(),
        _refreshAccessToken = refreshAccessToken,
        _nativeIdleTimeoutSeconds = idleTimeoutSeconds,
        _nativeAbsoluteTimeoutSeconds = absoluteTimeoutSeconds,
        _nativeWarnAtSeconds = warnAtSeconds,
        _onForcedLogout = onForcedLogout;

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
    if (mode == SessionTimeoutMode.native) {
      await _extendNative();
    } else {
      await _extendWeb();
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
    if (mode == SessionTimeoutMode.native) {
      _bootstrapNative();
    } else {
      await _bootstrapWeb();
    }
  }

  Future<void> _bootstrapWeb() async {
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

  void _bootstrapNative() {
    if (_nativeIdleTimeoutSeconds == 0 && _nativeAbsoluteTimeoutSeconds == 0) {
      _enabled = false;
      notifyListeners();
      return;
    }
    _applyState(SessionState(
      idleRemainingSeconds: _nativeIdleTimeoutSeconds,
      absoluteRemainingSeconds: _nativeAbsoluteTimeoutSeconds,
      idleTimeoutSeconds: _nativeIdleTimeoutSeconds,
      absoluteTimeoutSeconds: _nativeAbsoluteTimeoutSeconds,
      warnAtSeconds: _nativeWarnAtSeconds,
    ));
  }

  Future<void> _extendWeb() async {
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

  Future<void> _extendNative() async {
    final refresh = _refreshAccessToken;
    if (refresh == null) return;
    final DateTime? newExp;
    try {
      newExp = await refresh();
    } catch (_) {
      // Keycloak rejected the refresh token (revoked / expired). The
      // session is dead; force logout via the consumer callback.
      _enabled = false;
      notifyListeners();
      _onForcedLogout?.call();
      return;
    }
    // Reset the local idle countdown. Cap at the configured idle
    // timeout so a long-lived access token (e.g. 5-min Keycloak
    // default) doesn't widen the compliance window beyond intent.
    final now = DateTime.now();
    final accessTokenLifeSec = newExp == null
        ? _nativeIdleTimeoutSeconds
        : newExp.difference(now).inSeconds;
    final idleRemaining = accessTokenLifeSec < _nativeIdleTimeoutSeconds
        ? accessTokenLifeSec
        : _nativeIdleTimeoutSeconds;
    final absoluteRemaining = _absoluteExpiresAt.difference(now).inSeconds;
    _applyState(SessionState(
      idleRemainingSeconds: idleRemaining < 0 ? 0 : idleRemaining,
      absoluteRemainingSeconds: absoluteRemaining < 0 ? 0 : absoluteRemaining,
      idleTimeoutSeconds: _nativeIdleTimeoutSeconds,
      absoluteTimeoutSeconds: _nativeAbsoluteTimeoutSeconds,
      warnAtSeconds: _nativeWarnAtSeconds,
    ));
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
    _tickTimer = Timer.periodic(tick, (_) {
      // On native, when the idle countdown or the absolute timeout
      // elapses, the user has not been active for the full window
      // and there's no point in waiting for the next activity event
      // — force a logout so the login screen lands.
      if (mode == SessionTimeoutMode.native &&
          _enabled &&
          (idleRemainingSeconds <= 0 || absoluteRemainingSeconds <= 0)) {
        _enabled = false;
        _tickTimer?.cancel();
        _tickTimer = null;
        notifyListeners();
        _onForcedLogout?.call();
        return;
      }
      notifyListeners();
    });
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

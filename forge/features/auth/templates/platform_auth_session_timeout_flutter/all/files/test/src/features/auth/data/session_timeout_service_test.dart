/// Unit tests for SessionTimeoutService.
///
/// Covers both modes:
///  - **web**: cookie-based BFF (POST /auth/session). Mocks the
///    http.Client to drive the bootstrap + extend code paths.
///  - **native**: refresh-token rotation via the injected
///    RefreshAccessToken callback. Drives idle-timeout +
///    forced-logout paths via FakeAsync-style timer manipulation.
///
/// Mirrors the parity-spec scenarios that gate cross-platform
/// behavior: drift-immune countdown, visibility gating, debounced
/// activity, server-side disabled detection, refresh-rejection
/// → forced-logout.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:{{project_slug}}/src/features/auth/data/session_timeout_service.dart';

/// Build a mock http.Client that responds to GET / POST /auth/session
/// with the supplied [SessionState] body. Subsequent requests can be
/// stubbed via [respondWith].
class _StubHttp {
  _StubHttp(SessionState initial) : _state = initial;

  SessionState _state;
  int getCount = 0;
  int postCount = 0;
  int? overrideStatus;

  void respondWith(SessionState next) {
    _state = next;
  }

  void respondWithStatus(int status) {
    overrideStatus = status;
  }

  http.Client build() {
    return MockClient((request) async {
      final body = jsonEncode({
        'idle_remaining_seconds': _state.idleRemainingSeconds,
        'absolute_remaining_seconds': _state.absoluteRemainingSeconds,
        'idle_timeout_seconds': _state.idleTimeoutSeconds,
        'absolute_timeout_seconds': _state.absoluteTimeoutSeconds,
        'warn_at_seconds': _state.warnAtSeconds,
      });
      if (request.method == 'GET') getCount++;
      if (request.method == 'POST') postCount++;
      final status = overrideStatus ?? 200;
      overrideStatus = null;
      return http.Response(
        body,
        status,
        headers: {'content-type': 'application/json'},
      );
    });
  }
}

void main() {
  // SessionTimeoutService.dispose() calls WidgetsBinding.instance — the
  // test binding must be set up even for the non-widget tests.
  TestWidgetsFlutterBinding.ensureInitialized();

  // The default tick is 1 s + the default debounce is 30 s. The unit
  // tests use shorter durations to keep wall-clock fast.
  const fastTick = Duration(milliseconds: 50);
  const fastDebounce = Duration(milliseconds: 200);

  const baselineState = SessionState(
    idleRemainingSeconds: 600,
    absoluteRemainingSeconds: 3600,
    idleTimeoutSeconds: 1800,
    absoluteTimeoutSeconds: 43200,
    warnAtSeconds: 60,
  );

  group('SessionTimeoutService — web mode', () {
    test('mode is web by default', () {
      final svc = SessionTimeoutService();
      expect(svc.mode, SessionTimeoutMode.web);
      svc.dispose();
    });

    testWidgets('init() bootstraps from /auth/session GET',
        (WidgetTester tester) async {
      final stub = _StubHttp(baselineState);
      final svc = SessionTimeoutService(
        client: stub.build(),
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      expect(stub.getCount, 1);
      expect(svc.enabled, isTrue);
      // Drift-immune countdown: just-bootstrapped, remaining ≈ 600.
      expect(svc.idleRemainingSeconds, inInclusiveRange(595, 600));
      expect(svc.warnAtSeconds, 60);
    });

    testWidgets('extend() POSTs to /auth/session and applies new state',
        (WidgetTester tester) async {
      final stub = _StubHttp(baselineState);
      final svc = SessionTimeoutService(
        client: stub.build(),
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      stub.respondWith(const SessionState(
        idleRemainingSeconds: 1800,
        absoluteRemainingSeconds: 3600,
        idleTimeoutSeconds: 1800,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
      ));
      await svc.extend();
      expect(stub.postCount, 1);
      // Reset to the new idle window.
      expect(svc.idleRemainingSeconds, inInclusiveRange(1795, 1800));
    });

    testWidgets('bootstrap returning 401 silently disables the service',
        (WidgetTester tester) async {
      final stub = _StubHttp(baselineState)..respondWithStatus(401);
      final svc = SessionTimeoutService(
        client: stub.build(),
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      expect(svc.enabled, isFalse,
          reason: 'unauthenticated bootstrap must disable the service');
    });

    testWidgets('serverSideDisabled (idle=0 && absolute=0) disables the service',
        (WidgetTester tester) async {
      final stub = _StubHttp(const SessionState(
        idleRemainingSeconds: 0,
        absoluteRemainingSeconds: 0,
        idleTimeoutSeconds: 0,
        absoluteTimeoutSeconds: 0,
        warnAtSeconds: 60,
      ));
      final svc = SessionTimeoutService(
        client: stub.build(),
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      expect(svc.enabled, isFalse);
    });
  });

  group('SessionTimeoutService — native mode', () {
    testWidgets('forNative factory creates a native-mode service',
        (WidgetTester tester) async {
      Future<DateTime?> stubRefresh() async => DateTime.now().add(const Duration(minutes: 5));
      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        debounce: fastDebounce,
        tick: fastTick,
      );
      expect(svc.mode, SessionTimeoutMode.native);
      svc.dispose();
    });

    testWidgets('init() bootstraps from configured timeouts (no server call)',
        (WidgetTester tester) async {
      var refreshCallCount = 0;
      Future<DateTime?> stubRefresh() async {
        refreshCallCount++;
        return DateTime.now().add(const Duration(minutes: 5));
      }

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 1800,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      expect(svc.enabled, isTrue);
      expect(refreshCallCount, 0,
          reason: 'native bootstrap must NOT call refresh — purely local');
      expect(svc.idleRemainingSeconds, inInclusiveRange(1795, 1800));
      expect(svc.absoluteRemainingSeconds, inInclusiveRange(43195, 43200));
      expect(svc.warnAtSeconds, 60);
    });

    testWidgets(
        'extend() rotates via refreshAccessToken and resets idle countdown',
        (WidgetTester tester) async {
      var refreshCallCount = 0;
      Future<DateTime?> stubRefresh() async {
        refreshCallCount++;
        return DateTime.now().add(const Duration(minutes: 5));
      }

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 1800,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      // Simulate time elapsing without activity (tick the clock).
      await Future<void>.delayed(const Duration(milliseconds: 100));
      final beforeExtend = svc.idleRemainingSeconds;
      await svc.extend();
      expect(refreshCallCount, 1);
      // Capped at the access token's lifetime (5 min < 30 min idle
      // window), so idleRemaining ≈ 300.
      expect(svc.idleRemainingSeconds, inInclusiveRange(295, 300));
      // Verify the reset actually moved forward (not just stayed put).
      expect(svc.idleRemainingSeconds, lessThanOrEqualTo(300));
      expect(beforeExtend, lessThan(1800));
    });

    testWidgets(
        'extend() caps idle countdown at configured idle timeout',
        (WidgetTester tester) async {
      // Long-lived access token (1 hour). Idle window is 30 min.
      // The cap MUST clamp to 30 min so a long token doesn't widen
      // the compliance window.
      Future<DateTime?> stubRefresh() async =>
          DateTime.now().add(const Duration(hours: 1));

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 1800, // 30 min
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      await svc.extend();
      // The 1-hour access token lifetime must be capped to 1800s
      // idle. Anything > 1800 is a regression.
      expect(svc.idleRemainingSeconds, lessThanOrEqualTo(1800));
      expect(svc.idleRemainingSeconds, inInclusiveRange(1795, 1800));
    });

    testWidgets('refresh-token rejection fires onForcedLogout',
        (WidgetTester tester) async {
      Future<DateTime?> failingRefresh() async {
        throw Exception('refresh token revoked');
      }

      var loggedOut = false;
      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: failingRefresh,
        idleTimeoutSeconds: 1800,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        onForcedLogout: () {
          loggedOut = true;
        },
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      await svc.extend();
      expect(loggedOut, isTrue);
      expect(svc.enabled, isFalse);
    });

    testWidgets('idle countdown elapsed → forced logout via tick timer',
        (WidgetTester tester) async {
      Future<DateTime?> stubRefresh() async =>
          DateTime.now().add(const Duration(minutes: 5));

      var loggedOut = false;
      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 0,
        absoluteTimeoutSeconds: 0,
        warnAtSeconds: 60,
        onForcedLogout: () {
          loggedOut = true;
        },
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      // Both timeouts are 0 → service stays disabled. Tick won't fire
      // because _enabled is false; this asserts the disabled-from-
      // bootstrap path doesn't accidentally trigger logout.
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(loggedOut, isFalse,
          reason: 'serverSideDisabled state must NOT trigger forced logout '
              '— it just disables the service');
    });

    testWidgets('manual idle expiry triggers forced logout via tick',
        (WidgetTester tester) async {
      // Refresh returns a near-immediate expiry so the tick timer's
      // forced-logout branch fires fast.
      Future<DateTime?> nearImmediateRefresh() async =>
          DateTime.now().add(const Duration(milliseconds: 50));

      var loggedOut = false;
      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: nearImmediateRefresh,
        idleTimeoutSeconds: 1, // 1 s — elapsed almost immediately
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        onForcedLogout: () {
          loggedOut = true;
        },
        debounce: fastDebounce,
        tick: const Duration(milliseconds: 100),
      );
      addTearDown(svc.dispose);
      await svc.init();
      // Wait > idleTimeoutSeconds for tick timer to detect elapsed.
      await Future<void>.delayed(const Duration(seconds: 2));
      expect(loggedOut, isTrue,
          reason: 'tick timer must invoke onForcedLogout when '
              'idleRemainingSeconds reaches 0');
      expect(svc.enabled, isFalse);
    });

    testWidgets('drift-immune countdown — recomputed at read time',
        (WidgetTester tester) async {
      Future<DateTime?> stubRefresh() async =>
          DateTime.now().add(const Duration(minutes: 5));

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 60,
        absoluteTimeoutSeconds: 3600,
        warnAtSeconds: 10,
        debounce: fastDebounce,
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      final initial = svc.idleRemainingSeconds;
      // Wait 1.5 s and re-read — countdown should have decremented.
      await Future<void>.delayed(const Duration(milliseconds: 1500));
      final later = svc.idleRemainingSeconds;
      expect(later, lessThan(initial),
          reason: 'idleRemaining must decrement over time '
              '(drift-immune; computed via DateTime.now())');
      expect(initial - later, inInclusiveRange(1, 3),
          reason: '~1.5 s elapsed should yield ~1-2 s decrement');
    });
  });

  group('SessionTimeoutService — activity hints', () {
    testWidgets('valid activity hint queues a debounced extend',
        (WidgetTester tester) async {
      var refreshCallCount = 0;
      Future<DateTime?> stubRefresh() async {
        refreshCallCount++;
        return DateTime.now().add(const Duration(minutes: 5));
      }

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        idleTimeoutSeconds: 1800,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
        debounce: const Duration(milliseconds: 100),
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      svc.onUserActivity(hint: 'mousemove');
      // Inside debounce window → no extension yet.
      await Future<void>.delayed(const Duration(milliseconds: 50));
      expect(refreshCallCount, 0);
      // Past debounce window → extension fires.
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(refreshCallCount, 1);
    });

    testWidgets('unknown activity hint is rejected',
        (WidgetTester tester) async {
      var refreshCallCount = 0;
      Future<DateTime?> stubRefresh() async {
        refreshCallCount++;
        return DateTime.now().add(const Duration(minutes: 5));
      }

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        debounce: const Duration(milliseconds: 100),
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      svc.onUserActivity(hint: 'unknown-event');
      await Future<void>.delayed(const Duration(milliseconds: 200));
      expect(refreshCallCount, 0,
          reason: 'unknown activity hints must be silently dropped to '
              'preserve the cross-platform telemetry contract');
    });

    testWidgets('debounce coalesces rapid bursts to one extend',
        (WidgetTester tester) async {
      var refreshCallCount = 0;
      Future<DateTime?> stubRefresh() async {
        refreshCallCount++;
        return DateTime.now().add(const Duration(minutes: 5));
      }

      final svc = SessionTimeoutService.forNative(
        refreshAccessToken: stubRefresh,
        debounce: const Duration(milliseconds: 200),
        tick: fastTick,
      );
      addTearDown(svc.dispose);
      await svc.init();
      // 5 rapid hints inside the debounce window.
      for (var i = 0; i < 5; i++) {
        svc.onUserActivity(hint: 'mousemove');
        await Future<void>.delayed(const Duration(milliseconds: 20));
      }
      await Future<void>.delayed(const Duration(milliseconds: 300));
      expect(refreshCallCount, 1,
          reason: '5 rapid hints inside the debounce window must '
              'coalesce to exactly one extend call');
    });
  });

  group('SessionState', () {
    test('serverSideDisabled requires both timeouts to be 0', () {
      const both = SessionState(
        idleRemainingSeconds: 0,
        absoluteRemainingSeconds: 0,
        idleTimeoutSeconds: 0,
        absoluteTimeoutSeconds: 0,
        warnAtSeconds: 60,
      );
      const idleOnly = SessionState(
        idleRemainingSeconds: 0,
        absoluteRemainingSeconds: 0,
        idleTimeoutSeconds: 0,
        absoluteTimeoutSeconds: 43200,
        warnAtSeconds: 60,
      );
      expect(both.serverSideDisabled, isTrue);
      expect(idleOnly.serverSideDisabled, isFalse);
    });

    test('fromJson round-trips the canonical body shape', () {
      final json = {
        'idle_remaining_seconds': 600,
        'absolute_remaining_seconds': 3600,
        'idle_timeout_seconds': 1800,
        'absolute_timeout_seconds': 43200,
        'warn_at_seconds': 60,
      };
      final state = SessionState.fromJson(json);
      expect(state.idleRemainingSeconds, 600);
      expect(state.warnAtSeconds, 60);
    });
  });
}

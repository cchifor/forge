import 'package:{{project_slug}}/src/features/auth/data/auth_repository.dart';
import 'package:{{project_slug}}/src/features/auth/domain/auth_state.dart';
import 'package:{{project_slug}}/src/features/auth/domain/token_pair.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';

import '../../../../fixtures/user.dart';
import '../../../../helpers/mocks.dart';

void main() {
  late MockDevAuthService mockDevService;
  late MockKeycloakAuthService mockKcService;
  late MockGatekeeperAuthService mockGkService;

  setUp(() {
    mockDevService = MockDevAuthService();
    mockKcService = MockKeycloakAuthService();
    mockGkService = MockGatekeeperAuthService();
  });

  group('AuthRepository (authDisabled=true)', () {
    late AuthRepository repo;

    setUp(() {
      repo = AuthRepository(
        devService: mockDevService,
        authDisabled: true,
        useGatekeeper: false,
      );
    });

    test('init() delegates to DevAuthService and returns authenticated', () async {
      when(() => mockDevService.init()).thenAnswer((_) async => testUser);
      when(() => mockDevService.accessToken).thenReturn('dev-token');

      final state = await repo.init();

      expect(state, isA<Authenticated>());
      expect((state as Authenticated).user.email, 'dev@localhost');
      expect(state.accessToken, 'dev-token');
      verify(() => mockDevService.init()).called(1);
    });

    test('init() returns unauthenticated when dev service returns null', () async {
      when(() => mockDevService.init()).thenAnswer((_) async => null);
      when(() => mockDevService.accessToken).thenReturn(null);

      final state = await repo.init();

      expect(state, isA<Unauthenticated>());
    });

    test('login() delegates to DevAuthService', () async {
      const tokenPair = TokenPair(accessToken: 'dev-token', refreshToken: null);
      when(() => mockDevService.login())
          .thenAnswer((_) async => (testUser, tokenPair));

      final state = await repo.login();

      expect(state, isA<Authenticated>());
      expect((state as Authenticated).user.email, 'dev@localhost');
      expect(repo.accessToken, 'dev-token');
      verify(() => mockDevService.login()).called(1);
    });

    test('logout() delegates to DevAuthService and clears token', () async {
      when(() => mockDevService.logout()).thenAnswer((_) async {});

      await repo.logout();

      expect(repo.accessToken, isNull);
      verify(() => mockDevService.logout()).called(1);
    });

    test('currentUser delegates to DevAuthService', () {
      when(() => mockDevService.currentUser).thenReturn(testUser);

      expect(repo.currentUser, testUser);
      verify(() => mockDevService.currentUser).called(1);
    });

    test('refreshAccessToken() returns null on dev/auth-disabled mode',
        () async {
      // Auth is disabled — refresh-token rotation is not applicable.
      // Returning null lets callers (session timeout, dio interceptor)
      // treat dev mode as "no-op". No service is consulted.
      final result = await repo.refreshAccessToken();

      expect(result, isNull);
      verifyNever(() => mockKcService.refreshAccessToken());
      verifyZeroInteractions(mockDevService);
    });
  });

  group('AuthRepository (authDisabled=false, native/Keycloak)', () {
    late AuthRepository repo;

    setUp(() {
      repo = AuthRepository(
        keycloakService: mockKcService,
        authDisabled: false,
        useGatekeeper: false,
      );
    });

    test('init() delegates to KeycloakAuthService', () async {
      when(() => mockKcService.init()).thenAnswer((_) async => testUser);
      when(() => mockKcService.accessToken).thenReturn('kc-token');

      final state = await repo.init();

      expect(state, isA<Authenticated>());
      expect(repo.accessToken, 'kc-token');
      verify(() => mockKcService.init()).called(1);
    });

    test('login() delegates to KeycloakAuthService', () async {
      const tokenPair = TokenPair(accessToken: 'kc-token', refreshToken: 'refresh');
      when(() => mockKcService.login())
          .thenAnswer((_) async => (testUser, tokenPair));

      final state = await repo.login();

      expect(state, isA<Authenticated>());
      expect(repo.accessToken, 'kc-token');
      verify(() => mockKcService.login()).called(1);
    });

    test('logout() delegates to KeycloakAuthService', () async {
      when(() => mockKcService.logout()).thenAnswer((_) async {});

      await repo.logout();

      expect(repo.accessToken, isNull);
      verify(() => mockKcService.logout()).called(1);
    });

    test('refreshAccessToken() delegates to KeycloakAuthService '
        'and updates internal accessToken cache', () async {
      final newExpiry = DateTime(2030, 1, 1, 12, 0);
      when(() => mockKcService.refreshAccessToken())
          .thenAnswer((_) async => newExpiry);
      when(() => mockKcService.accessToken).thenReturn('rotated-kc-token');

      final returnedExpiry = await repo.refreshAccessToken();

      expect(returnedExpiry, newExpiry,
          reason: 'expiry must come straight from the underlying service');
      expect(repo.accessToken, 'rotated-kc-token',
          reason: 'cached access token must be refreshed in lockstep so the '
              'next dio request injects the new Bearer');
      verify(() => mockKcService.refreshAccessToken()).called(1);
    });

    test('refreshAccessToken() propagates exceptions from KeycloakAuthService',
        () async {
      when(() => mockKcService.refreshAccessToken())
          .thenThrow(Exception('invalid_grant'));

      await expectLater(
        repo.refreshAccessToken(),
        throwsException,
        reason: 'a rejected refresh must surface so the caller (session '
            'timeout / 401 interceptor) can force-logout',
      );
    });
  });

  group('AuthRepository (authDisabled=false, web/Gatekeeper)', () {
    late AuthRepository repo;

    setUp(() {
      repo = AuthRepository(
        gatekeeperService: mockGkService,
        authDisabled: false,
        useGatekeeper: true,
      );
    });

    test('init() delegates to GatekeeperAuthService and reports cookie auth',
        () async {
      when(() => mockGkService.init()).thenAnswer((_) async => testUser);
      when(() => mockGkService.accessToken).thenReturn(null);

      final state = await repo.init();

      expect(state, isA<Authenticated>());
      expect(repo.accessToken, isNull,
          reason: 'cookie-based BFF auth carries no client-side bearer');
      verify(() => mockGkService.init()).called(1);
    });

    test('login() returns unauthenticated — UI handles browser redirect',
        () async {
      final state = await repo.login();

      expect(state, isA<Unauthenticated>(),
          reason: 'on web the login flow is a server-side redirect, not a '
              'client-side credential exchange');
    });

    test('logout() delegates to GatekeeperAuthService', () async {
      when(() => mockGkService.logout()).thenAnswer((_) async {});

      await repo.logout();

      verify(() => mockGkService.logout()).called(1);
    });

    test('refreshAccessToken() returns null on web — cookies handle rotation',
        () async {
      // BFF refresh happens server-side (Gatekeeper rotates the
      // access-token cookie). The client has nothing to refresh, so
      // GatekeeperAuthService is never consulted.
      final result = await repo.refreshAccessToken();

      expect(result, isNull);
      verifyZeroInteractions(mockGkService);
    });
  });
}

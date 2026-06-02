// Unit tests for KeycloakAuthService.
//
// Covers the public surface — login(), init(), refreshAccessToken(),
// logout() — by injecting a mocked FlutterAppAuth and a mocked
// secure storage. The new refreshAccessToken() method is the focus
// of the native auth-refresh feature.

import 'dart:convert';

import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:{{project_slug}}/src/core/config/env_config.dart';
import 'package:{{project_slug}}/src/features/auth/data/keycloak_auth_service.dart';

import '../../../../helpers/mocks.dart';

/// Build a structurally-valid JWT (header.payload.signature) carrying
/// the supplied claims as the payload. The signature segment is a
/// fixed placeholder — the JwtDecoder used by KeycloakAuthService does
/// not validate signatures, only base64url-decodes the payload.
String _buildJwt(Map<String, dynamic> claims) {
  String b64UrlEncode(String input) =>
      base64Url.encode(utf8.encode(input)).replaceAll('=', '');
  final header = b64UrlEncode(jsonEncode({'alg': 'RS256', 'typ': 'JWT'}));
  final payload = b64UrlEncode(jsonEncode(claims));
  return '$header.$payload.signature';
}

void main() {
  setUpAll(() {
    // Mocktail needs registered fallback values for any non-primitive
    // arg type used in matchers (any() / captureAny()).
    registerFallbackValue(
      AuthorizationTokenRequest('client', 'redirect', issuer: 'http://x'),
    );
    registerFallbackValue(
      TokenRequest('client', 'redirect', issuer: 'http://x'),
    );
  });

  late MockFlutterAppAuth mockAppAuth;
  late MockFlutterSecureStorage mockStorage;
  late EnvConfig config;
  late KeycloakAuthService service;

  setUp(() {
    mockAppAuth = MockFlutterAppAuth();
    mockStorage = MockFlutterSecureStorage();
    config = const EnvConfig(
      apiBaseUrl: 'http://localhost:8000',
      keycloakUrl: 'http://localhost:8080',
      keycloakRealm: 'forge',
      keycloakClientId: 'svc-frontend',
      authDisabled: false,
    );
    service = KeycloakAuthService(
      config: config,
      secureStorage: mockStorage,
      appAuth: mockAppAuth,
    );
    // Default storage stubs — overridden per-test as needed.
    when(() => mockStorage.write(
          key: any(named: 'key'),
          value: any(named: 'value'),
        )).thenAnswer((_) async {});
    when(() => mockStorage.delete(key: any(named: 'key')))
        .thenAnswer((_) async {});
  });

  group('refreshAccessToken (native auth feature)', () {
    test('throws StateError when no refresh token is stored', () async {
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => null);
      await expectLater(
        service.refreshAccessToken(),
        throwsA(isA<StateError>()),
      );
    });

    test('rotates the access token and returns the new expiry',
        () async {
      final claims = {
        'sub': '00000000-0000-0000-0000-000000000001',
        'email': 'test@localhost',
        'preferred_username': 'tester',
        'given_name': 'Test',
        'family_name': 'User',
        'realm_access': {
          'roles': ['user'],
        },
        'customer_id': '00000000-0000-0000-0000-000000000001',
      };
      final newAccessToken = _buildJwt(claims);
      final newExpiry = DateTime(2030, 1, 1, 12, 0);

      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'old-refresh-token');
      when(() => mockAppAuth.token(any())).thenAnswer(
        (_) async => TokenResponse(
          newAccessToken,
          'new-refresh-token',
          newExpiry,
          'id-token',
          'Bearer',
          ['openid'],
          {},
        ),
      );

      final returnedExpiry = await service.refreshAccessToken();

      expect(returnedExpiry, newExpiry,
          reason: 'returned expiry must match the new access token expiry');
      expect(service.accessToken, newAccessToken,
          reason: 'in-memory access token must be the rotated one');
      // Both tokens must be persisted (refresh tokens rotate on each
      // refresh response in Keycloak).
      verify(() => mockStorage.write(
            key: 'access_token',
            value: newAccessToken,
          )).called(1);
      verify(() => mockStorage.write(
            key: 'refresh_token',
            value: 'new-refresh-token',
          )).called(1);
    });

    test('uses stored refresh token in the TokenRequest',
        () async {
      final claims = {'sub': 'sub-1'};
      final accessToken = _buildJwt(claims);
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'stored-rt-abc');
      when(() => mockAppAuth.token(any())).thenAnswer(
        (_) async => TokenResponse(
          accessToken,
          'rotated-rt-xyz',
          DateTime(2030),
          null,
          'Bearer',
          ['openid'],
          null,
        ),
      );

      await service.refreshAccessToken();

      final captured =
          verify(() => mockAppAuth.token(captureAny())).captured;
      final request = captured.single as TokenRequest;
      expect(request.refreshToken, 'stored-rt-abc',
          reason: 'token request must carry the stored refresh token');
      expect(request.clientId, 'svc-frontend',
          reason: 'token request must use the configured client ID');
      expect(request.issuer, 'http://localhost:8080/realms/forge',
          reason: 'token request must point at the configured Keycloak issuer');
    });

    test('rethrows when Keycloak rejects the refresh token',
        () async {
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'expired-rt');
      when(() => mockAppAuth.token(any()))
          .thenThrow(Exception('invalid_grant'));

      await expectLater(
        service.refreshAccessToken(),
        throwsException,
      );
    });
  });

  group('init (cold-start refresh)', () {
    test('returns null when no tokens are stored', () async {
      when(() => mockStorage.read(key: 'access_token'))
          .thenAnswer((_) async => null);
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => null);

      final user = await service.init();

      expect(user, isNull);
      verifyNever(() => mockAppAuth.token(any()));
    });

    test('rotates via the refresh token when both are stored',
        () async {
      final claims = {
        'sub': 'sub-1',
        'email': 'a@b.c',
        'preferred_username': 'a',
        'given_name': 'A',
        'family_name': 'B',
        'realm_access': {'roles': []},
      };
      final accessToken = _buildJwt(claims);

      when(() => mockStorage.read(key: 'access_token'))
          .thenAnswer((_) async => 'old-at');
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'old-rt');
      when(() => mockAppAuth.token(any())).thenAnswer(
        (_) async => TokenResponse(
          accessToken,
          'new-rt',
          DateTime(2030),
          null,
          'Bearer',
          ['openid'],
          null,
        ),
      );

      final user = await service.init();

      expect(user, isNotNull);
      expect(user!.email, 'a@b.c');
      expect(service.accessToken, accessToken);
    });

    test('clears stored tokens when refresh fails', () async {
      when(() => mockStorage.read(key: 'access_token'))
          .thenAnswer((_) async => 'stale-at');
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'stale-rt');
      when(() => mockAppAuth.token(any()))
          .thenThrow(Exception('invalid_grant'));

      final user = await service.init();

      expect(user, isNull,
          reason: 'failed refresh on cold start must clear stored '
              'tokens and return unauthenticated');
      verify(() => mockStorage.delete(key: 'access_token')).called(1);
      verify(() => mockStorage.delete(key: 'refresh_token')).called(1);
    });
  });

  group('logout', () {
    test('clears stored tokens and in-memory state', () async {
      when(() => mockStorage.read(key: 'access_token'))
          .thenAnswer((_) async => 'at');
      when(() => mockStorage.read(key: 'refresh_token'))
          .thenAnswer((_) async => 'rt');
      when(() => mockAppAuth.token(any())).thenAnswer(
        (_) async => TokenResponse(
          _buildJwt({'sub': 'sub-1'}),
          'new-rt',
          DateTime(2030),
          null,
          'Bearer',
          ['openid'],
          null,
        ),
      );
      await service.init();
      expect(service.accessToken, isNotNull);

      await service.logout();

      expect(service.accessToken, isNull);
      expect(service.currentUser, isNull);
      verify(() => mockStorage.delete(key: 'access_token')).called(1);
      verify(() => mockStorage.delete(key: 'refresh_token')).called(1);
    });
  });
}

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:riverpod_annotation/riverpod_annotation.dart';

import '../../../api/client/dio_client.dart';
import '../../../core/storage/secure_storage_provider.dart';
import '../domain/auth_state.dart';
import '../domain/user_model.dart';
import 'dev_auth_service.dart';
import 'gatekeeper_auth_service.dart';
import 'keycloak_auth_service.dart';

part 'auth_repository.g.dart';

class AuthRepository {
  AuthRepository({
    DevAuthService? devService,
    KeycloakAuthService? keycloakService,
    GatekeeperAuthService? gatekeeperService,
    required bool authDisabled,
    required bool useGatekeeper,
  })  : _devService = devService,
        _keycloakService = keycloakService,
        _gatekeeperService = gatekeeperService,
        _authDisabled = authDisabled,
        _useGatekeeper = useGatekeeper;

  final DevAuthService? _devService;
  final KeycloakAuthService? _keycloakService;
  final GatekeeperAuthService? _gatekeeperService;
  final bool _authDisabled;
  final bool _useGatekeeper;

  String? _accessToken;

  String? get accessToken => _accessToken;

  Future<AuthState> init() async {
    if (_authDisabled) {
      final dev = _devService!;
      final user = await dev.init();
      _accessToken = dev.accessToken;
      return user != null
          ? AuthState.authenticated(
              user: user,
              accessToken: _accessToken ?? '',
            )
          : const AuthState.unauthenticated();
    }

    // Web behind Gatekeeper: auth is cookie-based
    if (_useGatekeeper) {
      final gk = _gatekeeperService!;
      final user = await gk.init();
      _accessToken = gk.accessToken; // null — cookies handle auth
      return user != null
          ? AuthState.authenticated(user: user, accessToken: '')
          : const AuthState.unauthenticated();
    }

    // Native: use Keycloak AppAuth PKCE flow
    final kc = _keycloakService!;
    final user = await kc.init();
    _accessToken = kc.accessToken;
    return user != null
        ? AuthState.authenticated(
            user: user,
            accessToken: _accessToken ?? '',
          )
        : const AuthState.unauthenticated();
  }

  Future<AuthState> login() async {
    if (_authDisabled) {
      final (user, tokenPair) = await _devService!.login();
      _accessToken = tokenPair.accessToken;
      return AuthState.authenticated(user: user, accessToken: _accessToken!);
    }

    if (_useGatekeeper) {
      // On web, login is a browser redirect — should not reach here.
      // The UI layer handles the redirect to /auth/login.
      return const AuthState.unauthenticated();
    }

    final (user, tokenPair) = await _keycloakService!.login();
    _accessToken = tokenPair.accessToken;
    return AuthState.authenticated(user: user, accessToken: _accessToken!);
  }

  Future<void> logout() async {
    _accessToken = null;
    if (_authDisabled) {
      await _devService!.logout();
    } else if (_useGatekeeper) {
      await _gatekeeperService!.logout();
      // Browser redirect to /logout is handled by the UI layer
    } else {
      await _keycloakService!.logout();
    }
  }

  /// Rotate the access token (native only).
  ///
  /// Returns the new access token's expiry timestamp. Used by the
  /// session-timeout service's native code path to extend the local
  /// idle countdown on user activity, and by the Dio auth interceptor
  /// to recover from a server-side 401.
  ///
  /// Returns ``null`` on dev / web (Gatekeeper-cookie) auth — those
  /// paths don't manage refresh tokens client-side, so callers should
  /// treat ``null`` as "not applicable" rather than failure.
  ///
  /// Throws when Keycloak rejects the refresh token (revoked /
  /// expired) — caller must logout and force re-login.
  Future<DateTime?> refreshAccessToken() async {
    if (_authDisabled || _useGatekeeper) return null;
    final kc = _keycloakService!;
    final expiresAt = await kc.refreshAccessToken();
    _accessToken = kc.accessToken;
    return expiresAt;
  }

  User? get currentUser {
    if (_authDisabled) return _devService?.currentUser;
    if (_useGatekeeper) return _gatekeeperService?.currentUser;
    return _keycloakService?.currentUser;
  }
}

@Riverpod(keepAlive: true)
AuthRepository authRepository(Ref ref) {
  final config = ref.watch(envConfigProvider);
  if (config.authDisabled) {
    return AuthRepository(
      devService: DevAuthService(),
      authDisabled: true,
      useGatekeeper: false,
    );
  }
  // On web, use Gatekeeper (cookie-based auth via Traefik ForwardAuth)
  if (kIsWeb) {
    return AuthRepository(
      gatekeeperService: GatekeeperAuthService(),
      authDisabled: false,
      useGatekeeper: true,
    );
  }
  // On native, use Keycloak AppAuth PKCE flow
  return AuthRepository(
    keycloakService: KeycloakAuthService(
      config: config,
      secureStorage: ref.watch(secureStorageProvider),
    ),
    authDisabled: false,
    useGatekeeper: false,
  );
}

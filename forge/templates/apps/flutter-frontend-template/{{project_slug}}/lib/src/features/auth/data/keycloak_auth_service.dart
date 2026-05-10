import 'package:flutter_appauth/flutter_appauth.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/config/env_config.dart';
import '../domain/token_pair.dart';
import '../domain/user_model.dart';
import 'jwt_decoder.dart';

class KeycloakAuthService {
  KeycloakAuthService({
    required EnvConfig config,
    required FlutterSecureStorage secureStorage,
  })  : _config = config,
        _secureStorage = secureStorage;

  final EnvConfig _config;
  final FlutterSecureStorage _secureStorage;
  final FlutterAppAuth _appAuth = const FlutterAppAuth();

  TokenPair? _tokenPair;
  User? _currentUser;

  static const _accessTokenKey = 'access_token';
  static const _refreshTokenKey = 'refresh_token';

  String get _issuer =>
      '${_config.keycloakUrl}/realms/${_config.keycloakRealm}';

  Future<User?> init() async {
    final storedAccess = await _secureStorage.read(key: _accessTokenKey);
    final storedRefresh = await _secureStorage.read(key: _refreshTokenKey);

    if (storedAccess == null || storedRefresh == null) return null;

    try {
      await _rotateFromRefreshToken(storedRefresh);
      return _currentUser;
    } catch (_) {
      await _clearTokens();
    }
    return null;
  }

  /// Rotate the access token using the stored refresh token.
  ///
  /// Used by the session-timeout service to extend the local idle
  /// countdown on user activity (replaces the BFF cookie-based POST
  /// /auth/session that the web variant fires) and by the API client's
  /// 401 interceptor to recover from a server-side expiry.
  ///
  /// Returns the new access token's expiry timestamp. The caller resets
  /// its local idle-countdown anchor against this value.
  ///
  /// Throws when:
  /// - no refresh token is stored locally (caller must trigger login),
  /// - Keycloak rejects the refresh token (revoked / expired / signed
  ///   out elsewhere) — caller must clear tokens and force login.
  Future<DateTime?> refreshAccessToken() async {
    final storedRefresh = await _secureStorage.read(key: _refreshTokenKey);
    if (storedRefresh == null) {
      throw StateError('refreshAccessToken called with no stored refresh token');
    }
    await _rotateFromRefreshToken(storedRefresh);
    return _tokenPair?.expiresAt;
  }

  Future<void> _rotateFromRefreshToken(String refreshToken) async {
    final result = await _appAuth.token(
      TokenRequest(
        _config.keycloakClientId,
        'com.example.flutterfrontend:/callback',
        issuer: _issuer,
        refreshToken: refreshToken,
      ),
    );
    await _handleTokenResponse(result);
  }

  Future<(User, TokenPair)> login() async {
    final result = await _appAuth.authorizeAndExchangeCode(
      AuthorizationTokenRequest(
        _config.keycloakClientId,
        'com.example.flutterfrontend:/callback',
        issuer: _issuer,
        scopes: ['openid'],
        additionalParameters: {'kc_idp_hint': ''},
      ),
    );

    await _handleTokenResponse(result);
    return (_currentUser!, _tokenPair!);
  }

  Future<void> logout() async {
    await _clearTokens();
    _tokenPair = null;
    _currentUser = null;
  }

  String? get accessToken => _tokenPair?.accessToken;
  User? get currentUser => _currentUser;

  Future<void> _handleTokenResponse(TokenResponse response) async {
    _tokenPair = TokenPair(
      accessToken: response.accessToken!,
      refreshToken: response.refreshToken,
      expiresAt: response.accessTokenExpirationDateTime,
    );

    await _secureStorage.write(
      key: _accessTokenKey,
      value: response.accessToken,
    );
    if (response.refreshToken != null) {
      await _secureStorage.write(
        key: _refreshTokenKey,
        value: response.refreshToken,
      );
    }

    final claims = JwtDecoder.decode(response.accessToken!);
    _currentUser = User.fromJwtClaims(claims);
  }

  Future<void> _clearTokens() async {
    await _secureStorage.delete(key: _accessTokenKey);
    await _secureStorage.delete(key: _refreshTokenKey);
  }
}

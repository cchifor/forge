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
      final result = await _appAuth.token(
        TokenRequest(
          _config.keycloakClientId,
          'com.example.flutterfrontend:/callback',
          issuer: _issuer,
          refreshToken: storedRefresh,
        ),
      );

      await _handleTokenResponse(result);
      return _currentUser;
    } catch (_) {
      await _clearTokens();
    }
    return null;
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

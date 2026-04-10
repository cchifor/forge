import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:http/http.dart' as http;

import '../domain/token_pair.dart';
import '../domain/user_model.dart';

/// Web-only auth service that relies on Gatekeeper ForwardAuth.
///
/// When the Flutter app runs as a web app behind Traefik + Gatekeeper,
/// authentication is handled at the gateway level via HttpOnly cookies.
/// This service fetches user info from `/auth/userinfo` and triggers
/// login/logout via browser redirects.
class GatekeeperAuthService {
  User? _currentUser;

  Future<User?> init() async {
    try {
      final response = await http.get(Uri.parse('/auth/userinfo'));
      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        _currentUser = User(
          id: (data['userId'] ?? data['sub'] ?? '').toString(),
          email: (data['email'] ?? '').toString(),
          username:
              (data['preferredUsername'] ?? data['email'] ?? '').toString(),
          firstName: (data['givenName'] ?? '').toString(),
          lastName: (data['familyName'] ?? '').toString(),
          roles: (data['roles'] as List<dynamic>?)
                  ?.map((e) => e.toString())
                  .toList() ??
              [],
          customerId:
              (data['customerId'] ?? data['userId'] ?? data['sub'] ?? '')
                  .toString(),
          orgId: data['orgId']?.toString(),
        );
        return _currentUser;
      }
    } catch (_) {
      // Not authenticated or network error
    }
    return null;
  }

  /// Login is handled via browser redirect to Gatekeeper.
  /// Returns a dummy token pair — the real auth is in HttpOnly cookies.
  Future<(User, TokenPair)> login() async {
    // This should not be called directly on web — the login page
    // redirects to /auth/login via JavaScript.
    throw UnsupportedError(
      'GatekeeperAuthService.login() should not be called directly. '
      'Use window.location.href redirect to /auth/login instead.',
    );
  }

  Future<void> logout() async {
    _currentUser = null;
    // Browser redirect to /logout is handled by the UI layer
  }

  /// No client-side token — auth is via HttpOnly cookies.
  String? get accessToken => null;

  User? get currentUser => _currentUser;
}

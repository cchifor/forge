{%- if include_auth %}
import 'package:{{project_slug}}/src/core/config/env_config.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('EnvConfig defaults', () {
    test('apiBaseUrl has template default', () {
      const config = EnvConfig();
      expect(config.apiBaseUrl, isNotEmpty);
    });

    test('authDisabled defaults to true', () {
      const config = EnvConfig();
      expect(config.authDisabled, isTrue);
    });
  });

  group('EnvConfig computed URLs', () {
    test('keycloakAuthUrl concatenates url, realm, and path', () {
      const config = EnvConfig(
        keycloakUrl: 'https://auth.example.com',
        keycloakRealm: 'my-realm',
        keycloakClientId: 'my-client',
      );
      expect(
        config.keycloakAuthUrl,
        'https://auth.example.com/realms/my-realm/protocol/openid-connect/auth',
      );
    });

    test('keycloakTokenUrl concatenates url, realm, and path', () {
      const config = EnvConfig(
        keycloakUrl: 'https://auth.example.com',
        keycloakRealm: 'my-realm',
        keycloakClientId: 'my-client',
      );
      expect(
        config.keycloakTokenUrl,
        'https://auth.example.com/realms/my-realm/protocol/openid-connect/token',
      );
    });

    test('keycloakLogoutUrl concatenates url, realm, and path', () {
      const config = EnvConfig(
        keycloakUrl: 'https://auth.example.com',
        keycloakRealm: 'my-realm',
        keycloakClientId: 'my-client',
      );
      expect(
        config.keycloakLogoutUrl,
        'https://auth.example.com/realms/my-realm/protocol/openid-connect/logout',
      );
    });
  });

  group('isDevelopment', () {
    test('returns true when authDisabled is true', () {
      const config = EnvConfig(
        authDisabled: true,
        keycloakUrl: '',
        keycloakRealm: '',
        keycloakClientId: '',
      );
      expect(config.isDevelopment, isTrue);
    });

    test('returns false when authDisabled is false', () {
      const config = EnvConfig(
        authDisabled: false,
        keycloakUrl: '',
        keycloakRealm: '',
        keycloakClientId: '',
      );
      expect(config.isDevelopment, isFalse);
    });
  });

  group('EnvConfig custom values', () {
    test('accepts all custom constructor parameters', () {
      const config = EnvConfig(
        apiBaseUrl: 'https://api.test.com',
        authDisabled: false,
        keycloakUrl: 'https://kc.test.com',
        keycloakRealm: 'test-realm',
        keycloakClientId: 'test-client',
      );
      expect(config.apiBaseUrl, 'https://api.test.com');
      expect(config.authDisabled, isFalse);
      expect(config.keycloakUrl, 'https://kc.test.com');
      expect(config.keycloakRealm, 'test-realm');
      expect(config.keycloakClientId, 'test-client');
    });
  });
}
{%- endif %}

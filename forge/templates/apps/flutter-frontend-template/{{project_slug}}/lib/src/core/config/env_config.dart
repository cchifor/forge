class EnvConfig {
  const EnvConfig({
    this.apiBaseUrl = '{{api_base_url}}',
    this.authDisabled = {% if include_auth %}true{% else %}true{% endif %},
{%- if include_auth %}
    this.keycloakUrl = '{{keycloak_url}}',
    this.keycloakRealm = '{{keycloak_realm}}',
    this.keycloakClientId = '{{keycloak_client_id}}',
{%- endif %}
  });

  factory EnvConfig.fromEnvironment() {
    return const EnvConfig(
      apiBaseUrl: String.fromEnvironment(
        'API_BASE_URL',
        defaultValue: '{{api_base_url}}',
      ),
      authDisabled: bool.fromEnvironment(
        'AUTH_DISABLED',
        defaultValue: {% if include_auth %}true{% else %}true{% endif %},
      ),
{%- if include_auth %}
      keycloakUrl: String.fromEnvironment(
        'KEYCLOAK_URL',
        defaultValue: '{{keycloak_url}}',
      ),
      keycloakRealm: String.fromEnvironment(
        'KEYCLOAK_REALM',
        defaultValue: '{{keycloak_realm}}',
      ),
      keycloakClientId: String.fromEnvironment(
        'KEYCLOAK_CLIENT_ID',
        defaultValue: '{{keycloak_client_id}}',
      ),
{%- endif %}
    );
  }

  final String apiBaseUrl;
  final bool authDisabled;
{%- if include_auth %}
  final String keycloakUrl;
  final String keycloakRealm;
  final String keycloakClientId;

  bool get isDevelopment => authDisabled;

  String get keycloakAuthUrl =>
      '$keycloakUrl/realms/$keycloakRealm/protocol/openid-connect/auth';

  String get keycloakTokenUrl =>
      '$keycloakUrl/realms/$keycloakRealm/protocol/openid-connect/token';

  String get keycloakLogoutUrl =>
      '$keycloakUrl/realms/$keycloakRealm/protocol/openid-connect/logout';
{%- endif %}
}

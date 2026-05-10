from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_serializer


class AuthConfig(BaseModel):
    server_url: HttpUrl = Field(
        ...,
        description=(
            "Trusted issuer URL — for the platform-auth model this is the "
            "Gatekeeper base URL whose ``/auth/jwks`` endpoint serves the "
            "verifying public key."
        ),
    )
    realm: str = Field(..., description="Auth realm.")
    client_id: str = Field(..., description="Client ID.")
    client_secret: SecretStr = Field(..., description="Client Secret.")
    enabled: bool = Field(True, description="Enable authentication.")
    audience: str = Field(default="service-api", description="Expected token audience.")
    jwks_uri: HttpUrl | None = Field(
        default=None,
        description=(
            "Optional JWKS URI override. Defaults to "
            "``<server_url>/auth/jwks`` (the platform-auth Gatekeeper "
            "convention) when omitted."
        ),
    )

    @field_serializer("client_secret")
    def serialize_password(self, v: SecretStr, _info) -> str:
        return v.get_secret_value()

    @property
    def auth_url(self) -> str:
        base = str(self.server_url).rstrip("/")
        return f"{base}/realms/{self.realm}/protocol/openid-connect/auth"

    @property
    def token_url(self) -> str:
        base = str(self.server_url).rstrip("/")
        return f"{base}/realms/{self.realm}/protocol/openid-connect/token"

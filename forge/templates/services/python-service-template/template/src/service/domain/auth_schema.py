from pydantic import BaseModel, Field


class KeycloakRealmAccess(BaseModel):
    roles: list[str] = Field(default_factory=list)


class TokenPayload(BaseModel):
    """Represents the raw JWT payload structure."""

    sub: str
    email: str | None = None
    preferred_username: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    realm_access: KeycloakRealmAccess = Field(default_factory=KeycloakRealmAccess)
    azp: str | None = None
    org_id: str | None = None
    customer_id: str | None = None

    model_config = {"extra": "ignore"}

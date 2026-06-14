"""``weld.core.domain.user.User`` — verified-identity user (matrix-CI stub).

Field set matches what the auth fragment constructs from a Keycloak token
+ what call sites consume (``customer_id``, ``id``, ``roles``, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class User:
    id: Any = ""
    username: str = ""
    email: str = ""
    first_name: str = ""
    last_name: str = ""
    roles: list[str] = field(default_factory=list)
    customer_id: Any = ""
    org_id: Any = None
    service_account: bool = False
    token: dict[str, Any] = field(default_factory=dict)
    subject: str = ""
    tenant_id: Any = None
    scopes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

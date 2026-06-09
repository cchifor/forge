"""Unit tests for the schema-per-tenant tenant-resolution runtime.

Shipped by ``database.multitenancy=schema_per_tenant``. Covers the env-driven
config, the three resolution strategies, schema-name validation, and the
hook's no-op-off-Postgres behaviour. The engine ``begin`` listener +
``provision_tenant_schema`` are exercised at integration time against a real
Postgres; here we assert the imperative seams.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.core.tenancy.config import (
    DEFAULT_SCHEMA_PREFIX,
    TenancyConfigError,
    TenancySettings,
    load_tenancy_settings,
)
from app.core.tenancy.resolver import TenantResolver
from app.core.tenancy.schema import (
    TenantSchemaHook,
    bind_tenant_search_path,
    current_tenant_var,
    schema_name_for,
)


def _request(*, headers=None, identity=None, app_state=None):
    state = SimpleNamespace(identity=identity)
    app = SimpleNamespace(state=SimpleNamespace(**(app_state or {})))
    return SimpleNamespace(headers=headers or {}, state=state, app=app)


# --- config ---------------------------------------------------------------- #


def test_settings_defaults_match_options() -> None:
    s = TenancySettings()
    assert s.resolution == "token_claim"
    assert s.claim_path == "tenant_id"
    assert s.header_name == "X-Tenant-ID"
    assert s.schema_prefix == DEFAULT_SCHEMA_PREFIX == "tenant_"


def test_settings_rejects_bad_strategy() -> None:
    with pytest.raises(TenancyConfigError):
        TenancySettings(resolution="nope")


def test_settings_rejects_bad_prefix() -> None:
    # Must start with a letter (a schema name can't begin with a digit/underscore
    # and be a legal unquoted head; the prefix guarantees a letter lead).
    with pytest.raises(TenancyConfigError):
        TenancySettings(schema_prefix="1bad")
    with pytest.raises(TenancyConfigError):
        TenancySettings(schema_prefix="")
    with pytest.raises(TenancyConfigError):
        TenancySettings(schema_prefix="bad-prefix")  # hyphen not in [a-z0-9_]


def test_load_from_env() -> None:
    s = load_tenancy_settings(
        {
            "TENANT_RESOLUTION": "header",
            "TENANT_CLAIM_PATH": "org.id",
            "TENANT_HEADER_NAME": "X-Org",
            "TENANT_SCHEMA_PREFIX": "t_",
        }
    )
    assert s.resolution == "header"
    assert s.claim_path == "org.id"
    assert s.header_name == "X-Org"
    assert s.schema_prefix == "t_"


# --- schema name safety ---------------------------------------------------- #


def test_schema_name_for_slug_and_uuid() -> None:
    assert schema_name_for("acme") == "tenant_acme"
    # UUID hyphens survive (allow-listed); case is PRESERVED (no lowercasing —
    # lowercasing would be lossy and could collide two tenants).
    uid = "550E8400-E29B-41D4-A716-446655440000"
    assert schema_name_for(uid) == f"tenant_{uid}"


def test_schema_name_for_is_injective_on_case_and_whitespace() -> None:
    # The map MUST be injective: distinct ids → distinct schemas. Case is
    # preserved (not folded) and surrounding whitespace is rejected (not
    # trimmed) — either lossy transform would collapse distinct tenants.
    assert schema_name_for("ACME") != schema_name_for("acme")
    for bad in (" acme", "acme ", " acme "):
        with pytest.raises(TenancyConfigError):
            schema_name_for(bad)


def test_schema_name_for_custom_prefix() -> None:
    assert schema_name_for("acme", prefix="t_") == "t_acme"


def test_schema_name_for_rejects_unsafe_ids() -> None:
    # No lossy substitution — reject anything outside [A-Za-z0-9_-].
    for bad in ("", "  ", "a.b", "a;b", 'a"b', "a b", "drop table"):
        with pytest.raises(TenancyConfigError):
            schema_name_for(bad)


def test_schema_name_for_rejects_overlong() -> None:
    with pytest.raises(TenancyConfigError):
        schema_name_for("a" * 80)


# --- resolver strategies --------------------------------------------------- #


def test_resolve_header() -> None:
    r = TenantResolver(TenancySettings(resolution="header", header_name="X-Tenant-ID"))
    assert r.resolve(_request(headers={"X-Tenant-ID": "acme"})) == "acme"
    assert r.resolve(_request(headers={})) is None


def test_resolve_subdomain() -> None:
    r = TenantResolver(TenancySettings(resolution="subdomain"))
    assert r.resolve(_request(headers={"host": "acme.example.com"})) == "acme"
    assert r.resolve(_request(headers={"host": "example.com:8080"})) == "example"
    assert r.resolve(_request(headers={"host": "localhost"})) is None


def test_resolve_token_claim_builtin_dotpath() -> None:
    r = TenantResolver(TenancySettings(resolution="token_claim", claim_path="tenant_id"))
    identity = SimpleNamespace(claims={"tenant_id": "acme"})
    assert r.resolve(_request(identity=identity)) == "acme"
    # Missing identity ⇒ None (caller decides 401 vs anonymous).
    assert r.resolve(_request(identity=None)) is None


# --- imperative hook (workers) --------------------------------------------- #


class _FakeSession:
    def __init__(self, dialect: str) -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.executed: list = []

    async def execute(self, stmt, params=None):
        self.executed.append((stmt, params))


@pytest.mark.asyncio
async def test_hook_noop_off_postgres() -> None:
    hook = TenantSchemaHook(TenancySettings())
    session = _FakeSession("sqlite")
    await hook.bind(session, "acme")  # no-op off postgres
    await hook.clear(session)
    assert session.executed == []


@pytest.mark.asyncio
async def test_hook_binds_search_path_on_postgres() -> None:
    hook = TenantSchemaHook(TenancySettings())
    session = _FakeSession("postgresql")
    await hook.bind(session, "acme")
    assert len(session.executed) == 1
    _, params = session.executed[0]
    # The schema name inside the search_path value is double-quoted (a
    # hyphenated UUID schema would be an illegal unquoted identifier).
    assert params == {"sp": '"tenant_acme", public'}


@pytest.mark.asyncio
async def test_hook_bind_none_is_noop() -> None:
    hook = TenantSchemaHook(TenancySettings())
    session = _FakeSession("postgresql")
    await hook.bind(session, None)
    assert session.executed == []


@pytest.mark.asyncio
async def test_hook_rejects_unsafe_tenant_on_postgres() -> None:
    """An unsafe tenant id raises (the transaction fails) rather than routing
    to the wrong/shared schema."""
    hook = TenantSchemaHook(TenancySettings())
    session = _FakeSession("postgresql")
    with pytest.raises(TenancyConfigError):
        await hook.bind(session, "a;drop")
    assert session.executed == []


# --- UoW session binder (the post-auth request-path mechanism) ------------- #


class _Account:
    def __init__(self, customer_id):
        self.customer_id = customer_id


@pytest.mark.asyncio
async def test_binder_from_account_token_claim() -> None:
    """With no edge-resolved tenant, the binder routes search_path from the
    authenticated account — the path that makes token_claim work."""
    token = current_tenant_var.set(None)
    try:
        session = _FakeSession("postgresql")
        await bind_tenant_search_path(session, _Account("acme"))
        assert session.executed[0][1] == {"sp": '"tenant_acme", public'}
    finally:
        current_tenant_var.reset(token)


@pytest.mark.asyncio
async def test_binder_prefers_edge_resolved_contextvar() -> None:
    """Header/subdomain (edge-resolved ContextVar) wins over the account."""
    token = current_tenant_var.set("beta")
    try:
        session = _FakeSession("postgresql")
        await bind_tenant_search_path(session, _Account("acme"))
        assert session.executed[0][1] == {"sp": '"tenant_beta", public'}
    finally:
        current_tenant_var.reset(token)


@pytest.mark.asyncio
async def test_binder_fails_closed_without_tenant() -> None:
    """No ContextVar + no account (e.g. PublicUnitOfWork) ⇒ empty search_path,
    so unqualified app tables don't resolve (fail closed, not public)."""
    token = current_tenant_var.set(None)
    try:
        session = _FakeSession("postgresql")
        await bind_tenant_search_path(session, None)
        assert len(session.executed) == 1
        # An empty search_path value (the schema name isn't interpolated here).
        assert "'search_path', '', true" in str(session.executed[0][0]) or session.executed[0][1] in (
            None,
            {},
        )
    finally:
        current_tenant_var.reset(token)


@pytest.mark.asyncio
async def test_binder_noop_off_postgres() -> None:
    token = current_tenant_var.set("acme")
    try:
        session = _FakeSession("sqlite")
        await bind_tenant_search_path(session, _Account("acme"))
        assert session.executed == []
    finally:
        current_tenant_var.reset(token)

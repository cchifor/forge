"""Invariants for the ``database.multitenancy`` feature.

The discriminator controls tenant isolation in the generated persistence
layer:

- ``none`` (default): INERT — enables no fragments, changes no output. The
  golden-snapshot gate (``tests/test_golden_snapshots.py``) is the byte-exact
  guard; this file asserts the registry-level invariant.
- ``shared_rls``: Postgres Row-Level Security (Python tier-1). Ships the
  TenantResolver + GUC hook (RLS engine listener) + request middleware + an
  idempotent Alembic RLS migration.
- ``schema_per_tenant`` / ``db_per_tenant``: KNOWN-but-DEFERRED. Validation
  accepts the value; the resolver raises an explicit "not yet implemented"
  error rather than silently producing an un-isolated project.

This file gates:
  - option registration: default / values / requires_database / allowed_backends;
  - ``none`` enables nothing;
  - ``shared_rls`` on Python resolves the RLS fragment;
  - ``shared_rls`` on a Node / Rust project raises (allowed_backends enforced
    in the resolver);
  - the deferred strategies raise an explicit error (no silent no-op);
  - the tenant-resolution sub-options (defaults + types);
  - a dry-run render of a Python project with ``database.multitenancy=shared_rls``
    lands the RLS migration + GUC hook + resolver files and applies the
    middleware + listener injections;
  - the RLS migration SQL is idempotent (asserts the macro/structure);
  - composition with each auth provider (gatekeeper / oidc_generic / in_memory).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forge.config import BackendConfig, BackendLanguage, ProjectConfig
from forge.errors import OptionsError
from forge.fragments import FRAGMENT_REGISTRY
from forge.generator import generate
from forge.options import OPTION_REGISTRY
from forge.options._registry import OptionType

FRAGMENT_NAME = "multitenancy_rls_python"
SCHEMA_FRAGMENT_NAME = "multitenancy_schema_per_tenant_python"
OPTION_PATH = "database.multitenancy"

# Files the shared_rls fragment ADDS.
EXPECTED_FILES = (
    "src/app/core/tenancy/__init__.py",
    "src/app/core/tenancy/config.py",
    "src/app/core/tenancy/resolver.py",
    "src/app/core/tenancy/rls.py",
    "src/app/middleware/tenant_rls.py",
    "alembic/versions/0002_enable_rls.py",
    "tests/unit/test_tenancy.py",
)


def _py_cfg(*, multitenancy: str = "none", **kw) -> ProjectConfig:
    options = {"database.multitenancy": multitenancy}
    options.update(kw.pop("options", {}))
    return ProjectConfig(
        project_name="mt",
        backends=[
            BackendConfig(
                name="api",
                project_name="mt",
                language=BackendLanguage.PYTHON,
                features=["items"],
            )
        ],
        frontend=None,
        options=options,
        **kw,
    )


def _cfg_lang(lang: BackendLanguage, multitenancy: str) -> ProjectConfig:
    return ProjectConfig(
        project_name="mt",
        backends=[BackendConfig(name="api", project_name="mt", language=lang, features=["items"])],
        frontend=None,
        options={"database.multitenancy": multitenancy},
    )


def _fragment_root() -> Path:
    impl = FRAGMENT_REGISTRY[FRAGMENT_NAME].implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files"


# --------------------------------------------------------------------------- #
# Option registration
# --------------------------------------------------------------------------- #


def test_multitenancy_option_registered() -> None:
    assert OPTION_PATH in OPTION_REGISTRY
    opt = OPTION_REGISTRY[OPTION_PATH]
    assert opt.type is OptionType.ENUM
    assert opt.default == "none"
    assert opt.options == ("none", "shared_rls", "schema_per_tenant", "db_per_tenant")
    assert opt.requires_database is True
    assert opt.allowed_backends == (BackendLanguage.PYTHON,)


def test_multitenancy_enables_per_strategy() -> None:
    opt = OPTION_REGISTRY[OPTION_PATH]
    # shared_rls + schema_per_tenant each map to their fragment; none + the
    # still-deferred db_per_tenant map to nothing.
    assert opt.enables == {
        "shared_rls": (FRAGMENT_NAME,),
        "schema_per_tenant": (SCHEMA_FRAGMENT_NAME,),
    }
    assert "none" not in opt.enables
    assert "db_per_tenant" not in opt.enables


def test_tenant_resolution_suboption() -> None:
    opt = OPTION_REGISTRY["database.tenant_resolution"]
    assert opt.type is OptionType.ENUM
    assert opt.default == "token_claim"
    assert opt.options == ("token_claim", "header", "subdomain")
    # Resolution strategy never fans out to fragments — it configures the
    # rendered resolver, it doesn't select one.
    assert opt.enables == {}


def test_tenant_claim_path_and_header_suboptions() -> None:
    claim = OPTION_REGISTRY["database.tenant_claim_path"]
    assert claim.type is OptionType.STR
    assert claim.default == "tenant_id"
    header = OPTION_REGISTRY["database.tenant_header_name"]
    assert header.type is OptionType.STR
    assert header.default == "X-Tenant-ID"


def test_none_is_inactive_value() -> None:
    """The default ``none`` must not register as active (so it never trips the
    requires_database / allowed_backends walkers — the inert guarantee)."""
    opt = OPTION_REGISTRY[OPTION_PATH]
    assert opt.is_active_value("none") is False
    assert opt.is_active_value("shared_rls") is True


# --------------------------------------------------------------------------- #
# Resolver behaviour
# --------------------------------------------------------------------------- #


def test_none_enables_nothing() -> None:
    from forge.capability_resolver import resolve

    for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
        plan = resolve(_cfg_lang(lang, "none"))
        names = {rf.fragment.name for rf in plan.ordered}
        assert FRAGMENT_NAME not in names, f"none must enable no fragment on {lang.value}"


def test_shared_rls_on_python_resolves_fragment() -> None:
    from forge.capability_resolver import resolve

    plan = resolve(_py_cfg(multitenancy="shared_rls"))
    names = {rf.fragment.name for rf in plan.ordered}
    assert FRAGMENT_NAME in names


@pytest.mark.parametrize("lang", [BackendLanguage.NODE, BackendLanguage.RUST])
def test_shared_rls_on_non_python_raises(lang: BackendLanguage) -> None:
    """allowed_backends enforcement in the resolver."""
    from forge.capability_resolver import resolve

    with pytest.raises(OptionsError) as exc:
        resolve(_cfg_lang(lang, "shared_rls"))
    msg = str(exc.value)
    assert "database.multitenancy" in msg
    assert "python" in msg


def test_deferred_strategy_raises_explicitly() -> None:
    """db_per_tenant is recognised but raises a clear not-implemented error —
    never a silent no-op. (schema_per_tenant is now implemented.)"""
    from forge.capability_resolver import resolve

    with pytest.raises(OptionsError) as exc:
        resolve(_py_cfg(multitenancy="db_per_tenant"))
    msg = str(exc.value)
    assert "not-yet-implemented" in msg.lower() or "not yet implemented" in msg.lower()
    # Points at the implemented alternatives.
    assert "shared_rls" in msg
    assert "schema_per_tenant" in msg


def test_deferred_value_accepted_by_value_validation() -> None:
    """The value must be in the option's allowed set (validation accepts it);
    only the resolver refuses to GENERATE it."""
    OPTION_REGISTRY[OPTION_PATH].validate_value("db_per_tenant")


def test_schema_per_tenant_no_longer_deferred() -> None:
    """schema_per_tenant now resolves its fragment instead of raising."""
    from forge.capability_resolver import resolve

    plan = resolve(_py_cfg(multitenancy="schema_per_tenant"))
    names = {rf.fragment.name for rf in plan.ordered}
    assert SCHEMA_FRAGMENT_NAME in names
    assert FRAGMENT_NAME not in names  # the two are mutually exclusive


def test_default_value_does_not_trip_allowed_backends() -> None:
    """A persisted default (origin='default') must never hard-error even on a
    non-python backend — only a user selection does."""
    from forge.capability_resolver import resolve

    cfg = ProjectConfig(
        project_name="mt",
        backends=[
            BackendConfig(
                name="api", project_name="mt", language=BackendLanguage.NODE, features=["items"]
            )
        ],
        frontend=None,
        options={"database.multitenancy": "none"},
        option_origins={"database.multitenancy": "default"},
    )
    plan = resolve(cfg)  # must not raise
    assert FRAGMENT_NAME not in {rf.fragment.name for rf in plan.ordered}


# --------------------------------------------------------------------------- #
# Shipped-file structure + migration idempotency
# --------------------------------------------------------------------------- #


def test_fragment_python_only_backend_scoped() -> None:
    frag = FRAGMENT_REGISTRY[FRAGMENT_NAME]
    assert set(frag.implementations) == {BackendLanguage.PYTHON}
    assert frag.implementations[BackendLanguage.PYTHON].scope == "backend"
    assert frag.parity_tier == 3


def test_fragment_reads_resolution_options() -> None:
    impl = FRAGMENT_REGISTRY[FRAGMENT_NAME].implementations[BackendLanguage.PYTHON]
    assert "database.tenant_resolution" in impl.reads_options
    assert "database.tenant_claim_path" in impl.reads_options
    assert "database.tenant_header_name" in impl.reads_options


@pytest.mark.parametrize("rel", EXPECTED_FILES)
def test_fragment_ships_file(rel: str) -> None:
    assert (_fragment_root() / rel).is_file(), f"missing fragment file: {rel}"


def test_rls_migration_is_idempotent() -> None:
    """The migration must be re-runnable: ENABLE guarded by relrowsecurity,
    CREATE POLICY preceded by DROP POLICY IF EXISTS, and a fail-closed
    predicate."""
    mig = (_fragment_root() / "alembic/versions/0002_enable_rls.py").read_text(encoding="utf-8")
    # Idempotent ENABLE — guarded by pg_class.relrowsecurity.
    assert "relrowsecurity" in mig
    assert "ENABLE ROW LEVEL SECURITY" in mig
    # Idempotent policy — drop-if-exists then create.
    assert "DROP POLICY IF EXISTS" in mig
    assert "CREATE POLICY" in mig
    # The tenant predicate keys customer_id off the GUC.
    assert "current_setting" in mig
    assert "app.current_tenant" in mig
    assert "customer_id" in mig
    # FORCE so the owner (service role) is also constrained.
    assert "FORCE ROW LEVEL SECURITY" in mig
    # No-op on non-postgres (the chain runs under SQLite tests).
    assert "postgresql" in mig
    # Chains onto the base initial migration.
    assert "down_revision" in mig and '"0001"' in mig


def test_rls_hook_guc_matches_migration() -> None:
    """The runtime GUC constant must equal the migration's GUC — a drift here
    silently disables isolation."""
    rls = (_fragment_root() / "src/app/core/tenancy/rls.py").read_text(encoding="utf-8")
    mig = (_fragment_root() / "alembic/versions/0002_enable_rls.py").read_text(encoding="utf-8")
    assert 'TENANT_GUC = "app.current_tenant"' in rls
    assert 'TENANT_GUC = "app.current_tenant"' in mig


def test_rls_hook_noop_on_non_postgres() -> None:
    rls = (_fragment_root() / "src/app/core/tenancy/rls.py").read_text(encoding="utf-8")
    assert 'dialect.name != "postgresql"' in rls
    assert "register_rls_listener" in rls


def test_resolver_composes_with_claim_mapper() -> None:
    """token_claim resolution reuses the auth ClaimMapper when present."""
    resolver = (_fragment_root() / "src/app/core/tenancy/resolver.py").read_text(encoding="utf-8")
    assert "oidc_claim_mapper" in resolver  # reuse the provider's ClaimMapper
    assert "request.state" in resolver  # read the identity bound by auth middleware
    # The three strategies.
    assert "_from_token_claim" in resolver
    assert "_from_header" in resolver
    assert "_from_subdomain" in resolver


# --------------------------------------------------------------------------- #
# Render: full dry-run generation
# --------------------------------------------------------------------------- #


def test_render_lands_rls_files_and_injections(tmp_path: Path) -> None:
    cfg = ProjectConfig(
        project_name="mtr",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api", project_name="mtr", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        frontend=None,
        options={
            "database.multitenancy": "shared_rls",
            "database.tenant_resolution": "header",
            "database.tenant_header_name": "X-Org-ID",
        },
    )
    root = Path(generate(cfg, quiet=True, dry_run=True))
    backend = root / "services" / "api"

    # Resolver / GUC hook / migration land.
    assert (backend / "src/app/core/tenancy/resolver.py").is_file()
    assert (backend / "src/app/core/tenancy/rls.py").is_file()
    assert (backend / "src/app/core/tenancy/config.py").is_file()
    assert (backend / "alembic/versions/0002_enable_rls.py").is_file()
    assert (backend / "src/app/middleware/tenant_rls.py").is_file()

    # Middleware + listener injections applied.
    main_py = (backend / "src/app/main.py").read_text(encoding="utf-8")
    assert "from app.middleware.tenant_rls import TenantRLSMiddleware" in main_py
    assert "app.add_middleware(TenantRLSMiddleware)" in main_py
    # Option-driven render: the chosen header strategy is baked into the config.
    assert 'resolution="header"' in main_py
    assert 'header_name="X-Org-ID"' in main_py

    lifecycle = (backend / "src/app/core/lifecycle.py").read_text(encoding="utf-8")
    assert "register_rls_listener(db.engine)" in lifecycle


def test_shared_rls_excludes_tenant_management_service_backend(tmp_path: Path) -> None:
    """``shared_rls`` is project-global, but the RLS fragment lists the
    ``tenant-management-service`` variant in ``excluded_app_templates``: in a
    project mixing that control plane with a crud workload, RLS lands on the
    crud backend only. (The control plane isolates by realm + owns its own
    ``0002`` migration; an RLS ``0002`` would be a second Alembic head.)"""
    cfg = ProjectConfig(
        project_name="mtx",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="tms",
                project_name="mtx",
                language=BackendLanguage.PYTHON,
                app_template="tenant-management-service",
                features=["items"],
            ),
            BackendConfig(
                name="app",
                project_name="mtx",
                language=BackendLanguage.PYTHON,
                features=["items"],
            ),
        ],
        frontend=None,
        options={"database.multitenancy": "shared_rls"},
    )
    root = Path(generate(cfg, quiet=True, dry_run=True))

    # The crud workload gets the full RLS treatment.
    app = root / "services" / "app"
    assert (app / "src/app/core/tenancy/rls.py").is_file()
    assert (app / "src/app/middleware/tenant_rls.py").is_file()
    assert (app / "alembic/versions/0002_enable_rls.py").is_file()

    # The TMS control plane is excluded: no RLS tree, no RLS migration, and its
    # own 0002 survives as the single head off 0001.
    tms = root / "services" / "tms"
    assert not (tms / "src/app/core/tenancy").exists()
    assert not (tms / "src/app/middleware/tenant_rls.py").exists()
    assert not (tms / "alembic/versions/0002_enable_rls.py").exists()
    assert (tms / "alembic/versions/0002_tms_tables.py").is_file()


def test_render_default_none_no_tenancy_files(tmp_path: Path) -> None:
    """The inert default ships no tenancy tree (mirrors the golden gate)."""
    cfg = ProjectConfig(
        project_name="mtn",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api", project_name="mtn", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        frontend=None,
        options={},  # database.multitenancy defaults to none
    )
    root = Path(generate(cfg, quiet=True, dry_run=True))
    backend = root / "services" / "api"
    assert not (backend / "src/app/core/tenancy").exists()
    assert not (backend / "alembic/versions/0002_enable_rls.py").exists()
    assert not (backend / "src/app/middleware/tenant_rls.py").exists()


# --------------------------------------------------------------------------- #
# schema_per_tenant fragment
# --------------------------------------------------------------------------- #

# Files the schema_per_tenant fragment ADDS. No alembic migration (per-tenant
# schemas are materialized at runtime, not by a one-shot policy migration).
SCHEMA_EXPECTED_FILES = (
    "src/app/core/tenancy/__init__.py",
    "src/app/core/tenancy/config.py",
    "src/app/core/tenancy/resolver.py",
    "src/app/core/tenancy/schema.py",
    "src/app/core/tenancy/SCHEMA_PER_TENANT.md",
    "src/app/middleware/tenant_schema.py",
    "tests/unit/test_tenancy.py",
)


def _schema_fragment_root() -> Path:
    impl = FRAGMENT_REGISTRY[SCHEMA_FRAGMENT_NAME].implementations[BackendLanguage.PYTHON]
    return Path(impl.fragment_dir) / "files"


def test_schema_fragment_python_only_backend_scoped() -> None:
    frag = FRAGMENT_REGISTRY[SCHEMA_FRAGMENT_NAME]
    assert set(frag.implementations) == {BackendLanguage.PYTHON}
    assert frag.implementations[BackendLanguage.PYTHON].scope == "backend"
    # Same control-plane exemption as the RLS fragment.
    assert frag.excluded_app_templates == ("tenant-management-service",)


def test_schema_fragment_reads_resolution_options() -> None:
    impl = FRAGMENT_REGISTRY[SCHEMA_FRAGMENT_NAME].implementations[BackendLanguage.PYTHON]
    assert "database.tenant_resolution" in impl.reads_options
    assert "database.tenant_claim_path" in impl.reads_options
    assert "database.tenant_header_name" in impl.reads_options
    # Schema prefix surfaced as env (no forge option backs it).
    assert ("TENANT_SCHEMA_PREFIX", "tenant_") in impl.env_vars


@pytest.mark.parametrize("rel", SCHEMA_EXPECTED_FILES)
def test_schema_fragment_ships_file(rel: str) -> None:
    assert (_schema_fragment_root() / rel).is_file(), f"missing fragment file: {rel}"


def test_schema_fragment_ships_no_rls_migration() -> None:
    """schema_per_tenant provisions at runtime — it must NOT ship the RLS 0002
    (which would collide with the base 0001 chain on a different strategy)."""
    assert not (_schema_fragment_root() / "alembic/versions/0002_enable_rls.py").exists()


def test_schema_router_quotes_and_validates() -> None:
    """The search_path router must validate the tenant id (allow-list, not
    sanitize) and quote the identifier — the injection defense."""
    schema = (_schema_fragment_root() / "src/app/core/tenancy/schema.py").read_text(
        encoding="utf-8"
    )
    assert "SET LOCAL search_path TO" in schema
    assert "_quote_ident" in schema
    assert "schema_name_for" in schema
    # Allow-list regex (NOT a lossy sanitizer that could collide tenants).
    assert "[A-Za-z0-9_-]" in schema
    # 63-byte identifier limit enforced.
    assert "63" in schema
    # Provisioning + no-op-off-postgres.
    assert "provision_tenant_schema" in schema
    assert 'dialect.name != "postgresql"' in schema


def test_schema_router_fails_closed_on_missing_tenant() -> None:
    """No tenant bound ⇒ empty search_path (unqualified app tables invisible),
    NOT a fall-through to public. This is the security-critical posture: schema
    routing must not fail OPEN the way an unguarded search_path would."""
    schema = (_schema_fragment_root() / "src/app/core/tenancy/schema.py").read_text(
        encoding="utf-8"
    )
    # The fail-closed bind: empty search_path when the tenant ContextVar is None.
    assert "SET LOCAL search_path TO ''" in schema
    assert "FAIL CLOSED" in schema


def test_schema_resolver_code_matches_rls() -> None:
    """Both strategies ship the SAME resolver CODE — they only differ in the
    binding mechanism (and the module docstring, which is strategy-specific:
    schema routing does not fail closed the way RLS does). Compare everything
    from the first import onward so a logic drift is still caught."""
    def _code(path: Path) -> str:
        text = path.read_text(encoding="utf-8")
        return text[text.index("from __future__") :]

    rls = _code(_fragment_root() / "src/app/core/tenancy/resolver.py")
    schema = _code(_schema_fragment_root() / "src/app/core/tenancy/resolver.py")
    assert rls == schema


@pytest.mark.parametrize("lang", [BackendLanguage.NODE, BackendLanguage.RUST])
def test_schema_per_tenant_on_non_python_raises(lang: BackendLanguage) -> None:
    """allowed_backends enforcement applies to schema_per_tenant too."""
    from forge.capability_resolver import resolve

    with pytest.raises(OptionsError) as exc:
        resolve(_cfg_lang(lang, "schema_per_tenant"))
    assert "database.multitenancy" in str(exc.value)


def test_render_lands_schema_files_and_injections(tmp_path: Path) -> None:
    cfg = ProjectConfig(
        project_name="mts",
        output_dir=str(tmp_path),
        backends=[
            BackendConfig(
                name="api", project_name="mts", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        frontend=None,
        options={
            "database.multitenancy": "schema_per_tenant",
            "database.tenant_resolution": "subdomain",
        },
    )
    root = Path(generate(cfg, quiet=True, dry_run=True))
    backend = root / "services" / "api"

    assert (backend / "src/app/core/tenancy/schema.py").is_file()
    assert (backend / "src/app/core/tenancy/resolver.py").is_file()
    assert (backend / "src/app/core/tenancy/config.py").is_file()
    assert (backend / "src/app/middleware/tenant_schema.py").is_file()
    # No RLS migration shipped for this strategy.
    assert not (backend / "alembic/versions/0002_enable_rls.py").exists()

    main_py = (backend / "src/app/main.py").read_text(encoding="utf-8")
    assert "from app.middleware.tenant_schema import TenantSchemaMiddleware" in main_py
    assert "app.add_middleware(TenantSchemaMiddleware)" in main_py
    assert 'resolution="subdomain"' in main_py

    lifecycle = (backend / "src/app/core/lifecycle.py").read_text(encoding="utf-8")
    assert "register_search_path_listener(db.engine)" in lifecycle


# --------------------------------------------------------------------------- #
# Composition with auth providers
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("provider", "keycloak"),
    [("gatekeeper", True), ("oidc_generic", False), ("in_memory", False)],
)
def test_shared_rls_composes_with_auth_provider(provider: str, keycloak: bool) -> None:
    from forge.capability_resolver import resolve

    cfg = ProjectConfig(
        project_name="mt",
        backends=[
            BackendConfig(
                name="api", project_name="mt", language=BackendLanguage.PYTHON, features=["items"]
            )
        ],
        frontend=None,
        include_keycloak=keycloak,
        options={
            "database.multitenancy": "shared_rls",
            "auth.mode": "generate",
            "auth.provider": provider,
        },
    )
    plan = resolve(cfg)
    names = {rf.fragment.name for rf in plan.ordered}
    assert FRAGMENT_NAME in names, f"shared_rls must compose with auth.provider={provider}"
    assert plan.option_values["auth.provider"] == provider

"""Post-generation file strippers for stateless project modes.

Phase B1 completion: when ``database.mode=none`` is selected for a
Python backend, ``strip_python_database`` runs after the Copier base
template has been rendered but before the toolchain runs
``uv sync`` / ``ruff`` / tests. It:

* deletes DB-specific directories and files (alembic, SQLAlchemy
  models/repos/UoW, DB-backed services, DB unit tests);
* replaces a handful of IoC + lifecycle modules with stateless stubs;
* strips DB dependencies from the rendered ``pyproject.toml``;
* removes DB-related env vars from ``.env.example`` and the DB section
  of ``config/default.yaml``.

The result is a fastapi service scaffold with auth + middleware +
observability wired but no persistence layer — suitable for stateless
services (proxies, API aggregators, webhook receivers) or as a
starting point for bring-your-own-persistence backends.

Design notes
------------

Strippers are **orthogonal to fragments**. Fragments are additive:
they inject imports, copy files, append env vars. A stripper is the
opposite — it removes code that the base template unconditionally
emits. The cleanest split is to keep both surfaces rather than try to
shoehorn "delete" operations into the fragment pipeline.

The stateless replacement files live as constants in this module.
They're small enough (each well under 50 lines) that inlining them
avoids a second layer of file indirection.
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — import only for typing
    from forge.sync.provenance import ProvenanceCollector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File deletion targets
# ---------------------------------------------------------------------------

# Directories and files deleted wholesale when database.mode=none for a
# Python backend. Paths are relative to the backend's root directory
# (e.g. ``services/api/``). Order is irrelevant — the deletion loop
# handles missing paths as a no-op so upgrades from older templates
# degrade gracefully.
_PYTHON_DB_TARGETS: tuple[str, ...] = (
    # Migration + DB schema
    "alembic",
    "alembic.ini",
    # SQLAlchemy models + repositories + domain data layer
    "src/app/data",
    "src/app/cli/db.py",
    # DB-backed services
    "src/app/services/item_service.py",
    "src/app/services/health_service.py",
    # CRUD endpoints (items.py needs ItemService; tasks.py needs TaskService)
    "src/app/api/v1/endpoints/items.py",
    "src/app/api/v1/endpoints/tasks.py",
    # Shared DB infrastructure
    "src/app/core/db.py",
    "src/service/db",
    "src/service/repository",
    "src/service/uow",
    "src/service/tasks",
    # DB-dependent tests
    "tests/docker",
    "tests/unit/test_item_repository.py",
    "tests/unit/test_task_runner.py",
    "tests/unit/test_task_service.py",
    "tests/unit/test_task_models.py",
    "tests/unit/test_orm_models.py",
    "tests/unit/test_repository_aio.py",
    "tests/unit/test_db_config.py",
    "tests/integration/test_uow.py",
    # Service-test files whose entire body depends on stripped src/
    # modules (``health_service.py`` and ``item_service.py`` above).
    # Leaving them in place crashes pytest collection in stateless mode
    # with ``ModuleNotFoundError: No module named 'app.services.health_service'``.
    "tests/unit/test_health_service.py",
    "tests/unit/test_item_service.py",
)


# ---------------------------------------------------------------------------
# Stateless replacement source
# ---------------------------------------------------------------------------

_STATELESS_LIFECYCLE = '''\
"""Stateless application lifecycle.

Phase B1 stateless build: no database, no background task runner. The
bootstrap + lifespan are reduced to logging + DI container + auth setup
so the service boots cleanly without SQLAlchemy or alembic present.
"""

import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.core.config import Settings
from app.core.ioc import ALL_PROVIDERS
from forge_core.discovery import Discovery
from forge_core.security import auth
from forge_core.security.platform_auth_setup import build_auth_guard

logger = logging.getLogger(__name__)


class AppLifecycle:
    """Stateless orchestrator: build-time wiring + lifespan only."""

    @classmethod
    def bootstrap(cls, app: FastAPI, config: Settings) -> None:
        cls._setup_logging(config)
        logger.info(f"Bootstrapping {config.app.title} v{config.app.version}...")

        providers = [P() for P in ALL_PROVIDERS]
        container = make_async_container(*providers, context={Settings: config})
        setup_dishka(container, app)

        bundle = build_auth_guard(config.security.auth)
        if not config.security.auth.enabled:
            logger.warning(
                "Auth DISABLED — dev mode (synthetic user, no JWT verification)"
            )
        auth.initialize_auth(
            app,
            bundle=bundle,
            auth_url=config.security.auth.auth_url,
            token_url=config.security.auth.token_url,
            dev_mode=not config.security.auth.enabled,
        )

        logger.info("Application bootstrap complete. Waiting for server startup...")

    @classmethod
    @asynccontextmanager
    async def lifespan(cls, app: FastAPI) -> AsyncGenerator[None]:
        container: AsyncContainer | None = getattr(app.state, "dishka_container", None)
        if not container:
            raise RuntimeError(
                "DI Container not found in app.state. "
                "Did you forget to call AppLifecycle.bootstrap(app, config)?"
            )

        try:
            logger.info("Server starting up...")
            config = await container.get(Settings)

            if config.discovery.enabled:
                discovery_service = await container.get(Discovery)
                logger.info(f"Service registered: {discovery_service}")

            logger.info(
                f"Listening on {config.server.host}:{config.server.port}, (Press CTRL+C to quit)"
            )
            yield
        except Exception as exc:
            logger.critical(f"Critical Startup Failure: {exc}", exc_info=True)
            raise
        finally:
            logger.warning("Shutdown signal received. Initiating teardown...")
            await container.close()
            logger.info("Shutdown complete. Goodbye.")

    @staticmethod
    def _setup_logging(config: Settings) -> None:
        if not hasattr(config, "logging"):
            return
        try:
            logging_dict = config.logging.model_dump(by_alias=True, exclude_unset=True)
            logging_dict["disable_existing_loggers"] = False
            logging.config.dictConfig(logging_dict)
            logger.debug("Logging configuration applied.")
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            logging.error(f"Failed to apply logging config: {e}")
        # FORGE:LIFECYCLE_STARTUP
'''


_STATELESS_INFRA = '''\
"""Stateless infrastructure providers: discovery only (no database)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterable

from dishka import Provider, Scope, from_context, provide
from fastapi import Request

from app.core.config import Settings
from forge_core.discovery import Discovery

logger = logging.getLogger(__name__)


class InfraProvider(Provider):
    """Discovery only. Database providers are omitted in stateless mode."""

    scope = Scope.APP

    settings = from_context(provides=Settings, scope=Scope.APP)
    request = from_context(provides=Request, scope=Scope.REQUEST)

    @provide
    async def get_discovery(self, settings: Settings) -> AsyncIterable[Discovery]:
        if not settings.discovery.enabled:
            logger.info("Service discovery disabled.")
            yield Discovery(**settings.discovery.model_dump())
            return

        discovery = Discovery(**settings.discovery.model_dump())
        await discovery.register_async()
        yield discovery
        await discovery.unregister_async()
'''


_STATELESS_SERVICES = '''\
"""Stateless service providers.

The base template wires ItemService / HealthService / TaskService —
all of which depend on the SQLAlchemy session factory. In stateless
mode those services don't exist, so this provider is empty. Users
adding their own stateless services register them here.
"""

from __future__ import annotations

from dishka import Provider, Scope


class ServiceProvider(Provider):
    """Empty stateless provider. Register domain services here."""

    scope = Scope.APP
'''


_STATELESS_SECURITY = '''\
"""Stateless security provider: authentication only (no UoW).

The base template exposes ``AuthUnitOfWork`` / ``PublicUnitOfWork``
NewTypes backed by SQLAlchemy sessions. In stateless mode those
types don't exist; callers that need request-scoped tenancy without a
database should reach for the raw ``User`` and compose their own
persistence adapter.
"""

from __future__ import annotations

from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request

from forge_core.domain import context
from forge_core.domain.user import User
from forge_core.security.auth import authenticate_request


class SecurityProvider(Provider):
    """User authentication. UoW providers omitted in stateless mode."""

    scope = Scope.APP

    @provide(scope=Scope.REQUEST)
    async def get_current_user(self, request: Request) -> User:
        user = await authenticate_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required for this resource")
        context.set_context(customer_id=user.customer_id, user_id=user.id)
        return user
'''


_STATELESS_IOC_INIT = '''\
"""Stateless DI providers — InfraProvider + SecurityProvider + ServiceProvider.

The ``AuthUnitOfWork`` / ``PublicUnitOfWork`` types live in the
database-backed build only; in stateless mode imports from this module
should not reach for them.
"""

from app.core.ioc.infra import InfraProvider
from app.core.ioc.security import SecurityProvider
from app.core.ioc.services import ServiceProvider

ALL_PROVIDERS = (InfraProvider, SecurityProvider, ServiceProvider)

__all__ = [
    "ALL_PROVIDERS",
    "InfraProvider",
    "SecurityProvider",
    "ServiceProvider",
]
'''


_STATELESS_HEALTH_ENDPOINT = '''\
"""Stateless health endpoints — liveness only.

The base template's ``readiness_probe`` queries a SQLAlchemy-backed
HealthService through a PublicUnitOfWork. With no database in the
project, there's nothing to verify downstream — liveness is all the
orchestrator gets, and a stub readiness returns UP unconditionally.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/live")
async def liveness_probe():
    return {"status": "UP"}


@router.get("/ready")
async def readiness_probe():
    return {"status": "UP", "database": "not-configured"}
'''


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


# Files written / rewritten by strip_python_database. Used by
# _refresh_provenance_after_strip to update collector hashes after all the
# strippers have run. Keep this list in sync with _write_stateless_replacements
# + the in-place text strippers invoked from strip_python_database below.
_STRIPPER_TOUCHED_FILES: tuple[str, ...] = (
    # Stateless replacement files (full-file writes)
    "src/app/core/lifecycle.py",
    "src/app/core/ioc/infra.py",
    "src/app/core/ioc/services.py",
    "src/app/core/ioc/security.py",
    "src/app/core/ioc/__init__.py",
    "src/app/api/v1/endpoints/health.py",
    # In-place regex rewrites
    "src/app/api/v1/api.py",
    "pyproject.toml",
    ".env.example",
    "config/default.yaml",
    "src/app/core/config/domain.py",
    "src/app/core/config/loader.py",
    "src/app/cli/__init__.py",
    # In-place test strippers (_strip_test_config_dbconfig /
    # _strip_test_lifecycle_db_hooks below) — these rewrite the files but were
    # missing here, so their post-strip SHA was never re-recorded and a fresh
    # ``database.mode=none`` project failed day-0 ``forge --verify``.
    "tests/unit/test_config.py",
    "tests/unit/test_lifecycle.py",
)


def strip_python_database(
    backend_dir: Path,
    *,
    collector: ProvenanceCollector | None = None,
    template_name: str | None = None,
    template_version: str | None = None,
) -> None:
    """Remove DB-stack artefacts from a generated Python backend.

    Called when ``database.mode=none``. Safe to run more than once —
    every step is idempotent (deletions skip missing paths, replacements
    are full-file writes, regex strips are no-ops when the pattern has
    already been removed).

    When ``collector`` is provided, the provenance manifest is brought
    back into sync after the strip:

    * records for any path under :data:`_PYTHON_DB_TARGETS` are dropped
      (the on-disk paths were deleted), and
    * every file in :data:`_STRIPPER_TOUCHED_FILES` is re-recorded with
      ``origin="base-template"`` and the post-strip SHA — so downstream
      harvest / drift-verify sees a consistent manifest, and fragments
      that subsequently inject into these files (e.g. ``pii_redaction``
      into ``lifecycle.py``) correctly become the manifest owner.

    The ``collector`` hook is the structural counterpart to Cluster D of
    the matrix-nightly-fixes plan: ``strip_python_database`` now runs
    *before* fragment application so default-enabled fragments inject
    into the stateless lifecycle.py instead of being silently clobbered.
    See ``forge/generator.py`` for the pipeline order.
    """
    if not backend_dir.is_dir():
        raise ValueError(f"strip_python_database: not a directory: {backend_dir}")

    _delete_targets(backend_dir)
    _write_stateless_replacements(backend_dir)
    _strip_api_router(backend_dir / "src/app/api/v1/api.py")
    _strip_pyproject(backend_dir / "pyproject.toml")
    _strip_env_example(backend_dir / ".env.example")
    _strip_default_yaml(backend_dir / "config/default.yaml")
    _strip_config_domain(backend_dir / "src/app/core/config/domain.py")
    _strip_loader_db_refs(backend_dir / "src/app/core/config/loader.py")
    _strip_cli_init(backend_dir / "src/app/cli/__init__.py")
    _strip_test_config_dbconfig(backend_dir / "tests/unit/test_config.py")
    _strip_test_lifecycle_db_hooks(backend_dir / "tests/unit/test_lifecycle.py")

    if collector is not None:
        _refresh_provenance_after_strip(
            backend_dir,
            collector,
            template_name=template_name,
            template_version=template_version,
        )


def _refresh_provenance_after_strip(
    backend_dir: Path,
    collector: ProvenanceCollector,
    *,
    template_name: str | None,
    template_version: str | None,
) -> None:
    """Sync the provenance manifest with the post-strip state on disk."""
    try:
        backend_rel = backend_dir.relative_to(collector.project_root).as_posix()
    except ValueError:
        # backend_dir is outside project_root — caller passed an
        # incompatible collector; bail rather than corrupt the manifest.
        return
    # Drop records for paths the stripper deleted wholesale.
    for rel in _PYTHON_DB_TARGETS:
        prefix = f"{backend_rel}/{rel}" if backend_rel else rel
        collector.drop_records_under(prefix)
    # Re-record every file the stripper touched with the post-strip hash.
    for rel in _STRIPPER_TOUCHED_FILES:
        target = backend_dir / rel
        if target.is_file():
            collector.record(
                target,
                origin="base-template",
                template_name=template_name,
                template_version=template_version,
            )


def _delete_targets(backend_dir: Path) -> None:
    for rel in _PYTHON_DB_TARGETS:
        target = backend_dir / rel
        if target.is_dir():
            shutil.rmtree(target)
        elif target.is_file():
            target.unlink()


def _write_stateless_replacements(backend_dir: Path) -> None:
    replacements: dict[str, str] = {
        "src/app/core/lifecycle.py": _STATELESS_LIFECYCLE,
        "src/app/core/ioc/infra.py": _STATELESS_INFRA,
        "src/app/core/ioc/services.py": _STATELESS_SERVICES,
        "src/app/core/ioc/security.py": _STATELESS_SECURITY,
        "src/app/core/ioc/__init__.py": _STATELESS_IOC_INIT,
        "src/app/api/v1/endpoints/health.py": _STATELESS_HEALTH_ENDPOINT,
    }
    for rel, content in replacements.items():
        target = backend_dir / rel
        if not target.parent.exists():
            continue
        target.write_text(content, encoding="utf-8")


# -- regex strippers ---------------------------------------------------------


_API_IMPORT_RE = re.compile(r"^from app\.api\.v1\.endpoints import (.*)$", re.MULTILINE)
_API_INCLUDE_RE = re.compile(
    r"^api_router\.include_router\(\s*(items|tasks)\.router.*?\n",
    re.MULTILINE,
)


def _strip_api_router(path: Path) -> None:
    """Remove items / tasks imports + include_router calls from api.py."""
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")

    def _rewrite_import(match: re.Match[str]) -> str:
        modules = [m.strip() for m in match.group(1).split(",") if m.strip()]
        keep = [m for m in modules if m not in ("items", "tasks")]
        if not keep:
            return ""  # drop the line entirely
        return f"from app.api.v1.endpoints import {', '.join(keep)}"

    text = _API_IMPORT_RE.sub(_rewrite_import, text)
    text = _API_INCLUDE_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)  # tidy blank-line runs
    path.write_text(text, encoding="utf-8")


# TOML dependency removers ----------------------------------------------------
#
# The Python template's pyproject.toml lists deps like
#   "sqlalchemy[asyncio]>=2.0",
#   "asyncpg>=0.29",
#   "alembic>=1.13",
#   "psycopg[binary,pool]>=3.2",
# under ``[project] dependencies``. We remove by distribution name so
# version pins and extras don't matter.

_DB_DEP_NAMES = (
    "sqlalchemy",
    "asyncpg",
    "alembic",
    "psycopg",
    "psycopg2",
    "psycopg2-binary",
    "aiosqlite",
)


def _strip_pyproject(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    for dep in _DB_DEP_NAMES:
        # Match a dependency line: any leading whitespace, an opening
        # quote, the dep name (possibly followed by extras ``[...]`` and
        # version specifier), closing quote, optional comma, optional
        # trailing comment, trailing newline. Case-insensitive on name.
        pattern = re.compile(
            r"^[ \t]*[\"']" + re.escape(dep) + r"(?:\[[^\]]*\])?[^\"']*[\"'],?\s*(?:#[^\n]*)?\n",
            re.MULTILINE | re.IGNORECASE,
        )
        text = pattern.sub("", text)
    path.write_text(text, encoding="utf-8")


_ENV_DB_LINE_RE = re.compile(
    r"^(APP__DB__|DATABASE_URL|ALEMBIC_|POSTGRES_)[^\n]*\n",
    re.MULTILINE,
)


def _strip_env_example(path: Path) -> None:
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _ENV_DB_LINE_RE.sub("", text)
    # Also drop leading section comments that referenced the now-empty
    # database block ("# Database", "# PostgreSQL", etc.).
    text = re.sub(
        r"^#\s*(Database|PostgreSQL|DB connection)[^\n]*\n",
        "",
        text,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    path.write_text(text, encoding="utf-8")


def _strip_default_yaml(path: Path) -> None:
    """Remove the ``db:`` block from ``config/default.yaml``.

    The file is shipped as a literal YAML (``config/default.yaml`` or
    ``config/default.yaml.jinja`` rendered into place). We scan by
    top-level key, which is safe because the template uses 2-space
    indent with no tab characters.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Match a block starting with ``db:`` at column 0 and consume until
    # the next top-level key or end of file.
    pattern = re.compile(
        r"^db:[^\n]*\n(?:[ \t]+[^\n]*\n|\n)*",
        re.MULTILINE,
    )
    text = pattern.sub("", text)
    path.write_text(text, encoding="utf-8")


def _strip_config_domain(path: Path) -> None:
    """Remove ``DbConfig`` and its ``db: DbConfig`` field from the
    settings model.

    The pydantic ``Settings`` model has a ``db: DbConfig`` field; leaving
    it in would crash at startup (no default, required field). Remove
    both the class and the field.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Drop the class definition: ``class DbConfig(BaseModel):`` through
    # the next blank line before the following top-level ``class``.
    text = re.sub(
        r"^class DbConfig\(BaseModel\):\n(?:[ \t]+[^\n]*\n|\n)+(?=class |\Z)",
        "",
        text,
        flags=re.MULTILINE,
    )
    # Drop the field declaration on the Settings / AppSettings model.
    text = re.sub(r"^[ \t]+db:\s*DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


def _strip_loader_db_refs(path: Path) -> None:
    """Remove DbConfig imports + qualified field references from loader.py.

    Two cases handled:

    * Direct-import shape — ``from app.core.config.domain import DbConfig``
      (or a bundle import including ``DbConfig``). The first three regex
      strips below cover this.
    * Qualified-field shape — ``db: domain.DbConfig = domain.DbConfig()``
      on the Settings class, when loader.py imports via
      ``from . import domain, sources``. The shipped production loader.py
      uses this pattern; without the last regex the field survives
      ``_strip_config_domain``'s class removal and crashes at module load
      with ``AttributeError: module 'domain' has no attribute 'DbConfig'``.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"^from [^\n]*import[^\n]*DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    # Also strip ``, DbConfig`` out of longer import lines.
    text = re.sub(r",\s*DbConfig\b", "", text)
    text = re.sub(r"\bDbConfig,\s*", "", text)
    # Qualified Settings field — ``db: (domain.)?DbConfig = ...``.
    text = re.sub(r"^[ \t]+db:\s*(?:domain\.)?DbConfig[^\n]*\n", "", text, flags=re.MULTILINE)
    path.write_text(text, encoding="utf-8")


_CLI_DB_IMPORT_RE = re.compile(r"^from app\.cli\.db import [^\n]*\n", re.MULTILINE)
_CLI_DB_REGISTER_RE = re.compile(r"^cli\.add_typer\(\s*db_app[^\n]*\n", re.MULTILINE)


def _strip_test_lifecycle_db_hooks(path: Path) -> None:
    """Remove DB-hook lifecycle tests that don't apply to the stateless build.

    Two test methods exercise lifecycle hooks (``_on_startup`` /
    ``_on_shutdown``) that exist on the full DB-backed ``AppLifecycle``
    but were dropped from the stateless replacement (the stateless
    lifespan calls ``container.close()`` directly without a separate
    shutdown hook):

      - ``TestLifespan::test_calls_startup_and_shutdown`` — patches
        ``AppLifecycle._on_startup`` and ``._on_shutdown`` via
        ``patch.object``, which fails on AttributeError when the
        targets are missing.
      - ``TestShutdown::test_shutdown_closes_container`` — calls
        ``AppLifecycle._on_shutdown(container)`` directly.

    Surgically drop these two pieces; the rest of ``test_lifecycle.py``
    (bootstrap + lifespan-without-container coverage) still applies.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Drop the single failing TestLifespan method (decorators + multi-line
    # signature + body). ``[\s\S]*?`` (lazy) consumes the multi-line
    # parameter list across newlines until ``    ):`` closes it; the
    # trailing ``(?:        [^\n]*\n|\n)+`` then consumes the function
    # body until a less-indented line (next method or end of class).
    text = re.sub(
        r"\n    @pytest\.mark\.asyncio\n(?:    @patch\.object[^\n]*\n)+    async def test_calls_startup_and_shutdown\([\s\S]*?    \):\n(?:        [^\n]*\n|\n)+",
        "\n",
        text,
    )
    # Drop the entire TestShutdown class.
    text = re.sub(
        r"^class TestShutdown:\n(?:[ \t]+[^\n]*\n|\n)+(?=class |\Z)",
        "",
        text,
        flags=re.MULTILINE,
    )
    path.write_text(text, encoding="utf-8")


def _strip_test_config_dbconfig(path: Path) -> None:
    """Remove ``DbConfig`` references from ``tests/unit/test_config.py``.

    The test file imports ``DbConfig`` alongside ``AuditConfig`` and
    ``CorsConfig`` from ``app.core.config.domain`` and defines a
    ``TestDbConfig`` class. The non-DbConfig classes (``TestCorsConfig``,
    ``TestAuditConfig``) remain valuable in stateless mode, so this
    surgically drops only the DbConfig pieces rather than deleting the
    whole file (the wholesale-delete approach would lose coverage of the
    other two configs).
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    # Remove ``DbConfig`` from a bundle import like
    # ``from ... import AuditConfig, CorsConfig, DbConfig``.
    text = re.sub(r",\s*DbConfig\b", "", text)
    text = re.sub(r"\bDbConfig\s*,\s*", "", text)
    # Drop an entire ``class TestDbConfig:`` block — including any
    # decorators, body lines, and the trailing blank line(s) before the
    # next top-level ``class`` or end of file. Mirrors
    # ``_strip_config_domain``'s class-removal regex.
    text = re.sub(
        r"^class TestDbConfig:\n(?:[ \t]+[^\n]*\n|\n)+(?=class |\Z)",
        "",
        text,
        flags=re.MULTILINE,
    )
    path.write_text(text, encoding="utf-8")


def _strip_cli_init(path: Path) -> None:
    """Remove the ``app.cli.db`` import + Typer registration from cli/__init__.py.

    The base template ships ``src/app/cli/__init__.py`` with::

        from app.cli.db import db_app
        ...
        cli.add_typer(db_app, name="db", help="Database migrations")

    ``_PYTHON_DB_TARGETS`` already deletes ``src/app/cli/db.py`` itself, but
    without this complementary rewrite the import in ``cli/__init__.py``
    raises ``ModuleNotFoundError`` on first ``python -m app`` import.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    text = _CLI_DB_IMPORT_RE.sub("", text)
    text = _CLI_DB_REGISTER_RE.sub("", text)
    path.write_text(text, encoding="utf-8")

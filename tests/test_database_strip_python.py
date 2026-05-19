"""Phase B1 completion — ``strip_python_database`` tests.

Synthetic-tree tests: we build a fake Python backend directory
mirroring the template's DB-bearing layout, run
``strip_python_database`` on it, and assert every category of
transformation — deletions, stateless replacements, and text strips —
left the tree in the expected state.

This deliberately avoids invoking Copier (which would pull in the
Svelte ``npm install`` we already saw turn a 5-minute test into a
minutes-long build). The stripper operates on paths and file text;
the template just needs a convincing stand-in.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from forge.strippers import strip_python_database


# -- Helpers -----------------------------------------------------------------


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


_DOCSTRING_RE = re.compile(r'""".*?"""', re.DOTALL)


def _code_only(text: str) -> str:
    """Return ``text`` with triple-quoted docstrings removed.

    The stateless replacements include explanatory docstrings that
    legitimately mention the names they replace (e.g. "HealthService
    through a PublicUnitOfWork" in the stub health.py). Tests that check
    a name is absent from *code* need to ignore the docstring. This
    strip is crude (regex) but sufficient — the replacement stubs
    don't nest docstrings or embed triple quotes inside strings.
    """
    return _DOCSTRING_RE.sub("", text)


@pytest.fixture
def python_backend(tmp_path: Path) -> Path:
    """Build a synthetic Python backend matching the template's layout."""
    root = tmp_path / "api"
    root.mkdir()

    # Directories/files the stripper deletes wholesale.
    _write(root / "alembic" / "versions" / "0001_initial.py", "# migration\n")
    _write(root / "alembic.ini", "[alembic]\n")
    _write(root / "src/app/data/models/item.py", "import sqlalchemy\n")
    _write(root / "src/app/cli/db.py", "import alembic\n")
    _write(root / "src/app/services/item_service.py", "from app.data import *\n")
    _write(root / "src/app/services/health_service.py", "from service.uow.aio import *\n")
    _write(root / "src/app/api/v1/endpoints/items.py", "from app.services.item_service import *\n")
    _write(root / "src/app/api/v1/endpoints/tasks.py", "from service.tasks.service import *\n")
    _write(root / "src/app/core/db.py", "_session_factory = None\n")
    _write(root / "src/service/db/aio.py", "class AsyncDatabase: pass\n")
    _write(root / "src/service/repository/aio.py", "class Repo: pass\n")
    _write(root / "src/service/uow/aio.py", "class UoW: pass\n")
    _write(root / "src/service/tasks/runner.py", "class Runner: pass\n")
    _write(root / "tests/docker/test_migrations.py", "# skip\n")
    _write(root / "tests/unit/test_item_repository.py", "# skip\n")
    _write(root / "tests/unit/test_task_runner.py", "# skip\n")
    _write(root / "tests/unit/test_orm_models.py", "# skip\n")
    _write(root / "tests/integration/test_uow.py", "# skip\n")

    # Keep-me targets: the stripper writes stateless replacements here.
    _write(
        root / "src/app/core/lifecycle.py",
        'from service.db.aio import AsyncDatabase\n'
        'from service.tasks.runner import BackgroundTaskRunner\n'
        'class AppLifecycle:\n    pass\n',
    )
    _write(root / "src/app/core/ioc/__init__.py", "from app.core.ioc.security import AuthUnitOfWork\n")
    _write(root / "src/app/core/ioc/infra.py", "from service.db.aio import AsyncDatabase\n")
    _write(root / "src/app/core/ioc/services.py", "from service.tasks.service import TaskService\n")
    _write(root / "src/app/core/ioc/security.py", "from service.uow.aio import AsyncUnitOfWork\n")
    _write(
        root / "src/app/api/v1/endpoints/health.py",
        'from app.services.health_service import HealthService\n',
    )

    # Api router file — has items/tasks imports.
    _write(
        root / "src/app/api/v1/api.py",
        "from fastapi import APIRouter\n"
        "from app.api.v1.endpoints import admin, health, home, items, tasks\n"
        "\n"
        "api_router = APIRouter()\n"
        "api_router.include_router(home.router, tags=['home'])\n"
        "api_router.include_router(health.router, prefix='/health')\n"
        "api_router.include_router(items.router, prefix='/items')\n"
        "api_router.include_router(tasks.router, prefix='/tasks')\n"
        "api_router.include_router(admin.router, prefix='/admin')\n",
    )

    # pyproject.toml with DB deps mixed in with non-DB deps.
    _write(
        root / "pyproject.toml",
        '[project]\n'
        'dependencies = [\n'
        '    "fastapi>=0.115",\n'
        '    "pydantic>=2.9",\n'
        '    "sqlalchemy[asyncio]>=2.0",\n'
        '    "asyncpg>=0.29",\n'
        '    "alembic>=1.13",\n'
        '    "psycopg[binary,pool]>=3.2",\n'
        '    "uvicorn>=0.30",\n'
        ']\n',
    )

    # .env.example with DB vars + other vars.
    _write(
        root / ".env.example",
        "# Database\n"
        "APP__DB__URL=postgresql+asyncpg://postgres:postgres@localhost:5432/api\n"
        "APP__DB__POOL_SIZE=10\n"
        "DATABASE_URL=postgresql://postgres:postgres@localhost:5432/api\n"
        "\n"
        "# App\n"
        "APP__APP__TITLE=My Service\n"
        "APP__SERVER__PORT=5000\n",
    )

    # config/default.yaml with a db: block
    _write(
        root / "config/default.yaml",
        "app:\n"
        "  title: api\n"
        "  version: 0.1.0\n"
        "db:\n"
        "  url: sqlite+aiosqlite:///development.db\n"
        "  pool_size: 10\n"
        "server:\n"
        "  host: 0.0.0.0\n"
        "  port: 5000\n",
    )

    # config/domain.py with DbConfig
    _write(
        root / "src/app/core/config/domain.py",
        "from pydantic import BaseModel, Field\n"
        "\n"
        "class AppConfig(BaseModel):\n"
        "    title: str = 'api'\n"
        "\n"
        "class DbConfig(BaseModel):\n"
        "    url: str = Field('sqlite:///dev.db')\n"
        "    pool_size: int = 10\n"
        "\n"
        "class Settings(BaseModel):\n"
        "    app: AppConfig\n"
        "    db: DbConfig\n"
        "    port: int = 5000\n",
    )

    _write(
        root / "src/app/core/config/loader.py",
        "from app.core.config.domain import AppConfig, DbConfig, Settings\n"
        "\n"
        "def load() -> Settings:\n"
        "    return Settings(app=AppConfig(), db=DbConfig())\n",
    )

    # cli/__init__.py — registers db_app as a typer sub-command. The stripper
    # deletes cli/db.py wholesale; without a complementary rewrite here the
    # generated project crashes on first ``python -m app`` import.
    _write(
        root / "src/app/cli/__init__.py",
        "import typer\n"
        "\n"
        "from app.cli.db import db_app\n"
        "from app.cli.server import server_app\n"
        "# FORGE:CLI_IMPORTS\n"
        "\n"
        "cli = typer.Typer(name='app', help='Service CLI')\n"
        "cli.add_typer(server_app, name='server', help='Server management')\n"
        "cli.add_typer(db_app, name='db', help='Database migrations')\n"
        "# FORGE:CLI_REGISTRATION\n",
    )

    return root


# -- Deletion ----------------------------------------------------------------


class TestDeletions:
    def test_alembic_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        assert not (python_backend / "alembic").exists()
        assert not (python_backend / "alembic.ini").exists()

    def test_data_layer_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        assert not (python_backend / "src/app/data").exists()
        assert not (python_backend / "src/app/cli/db.py").exists()

    def test_db_backed_services_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        assert not (python_backend / "src/app/services/item_service.py").exists()
        assert not (python_backend / "src/app/services/health_service.py").exists()

    def test_crud_endpoints_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        assert not (python_backend / "src/app/api/v1/endpoints/items.py").exists()
        assert not (python_backend / "src/app/api/v1/endpoints/tasks.py").exists()

    def test_service_db_modules_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        for sub in ("db", "repository", "uow", "tasks"):
            assert not (python_backend / "src/service" / sub).exists()

    def test_db_tests_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        assert not (python_backend / "tests/docker").exists()
        for name in (
            "test_item_repository.py",
            "test_task_runner.py",
            "test_orm_models.py",
        ):
            assert not (python_backend / "tests/unit" / name).exists()
        assert not (python_backend / "tests/integration/test_uow.py").exists()


# -- Stateless replacements ---------------------------------------------------


class TestStatelessReplacements:
    def test_lifecycle_has_no_db_imports(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/core/lifecycle.py").read_text(encoding="utf-8")
        assert "service.db" not in text
        assert "BackgroundTaskRunner" not in text
        assert "class AppLifecycle" in text  # stub still defines the class

    def test_ioc_init_drops_unit_of_work_exports(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/core/ioc/__init__.py").read_text(encoding="utf-8")
        code = _code_only(text)
        assert "AuthUnitOfWork" not in code
        assert "PublicUnitOfWork" not in code
        assert "ALL_PROVIDERS" in code

    def test_ioc_infra_loses_asyncdatabase(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/core/ioc/infra.py").read_text(encoding="utf-8")
        code = _code_only(text)
        assert "AsyncDatabase" not in code
        assert "Discovery" in code  # discovery still provided

    def test_ioc_services_is_empty_provider(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/core/ioc/services.py").read_text(encoding="utf-8")
        code = _code_only(text)
        assert "TaskService" not in code
        assert "ItemService" not in code
        assert "class ServiceProvider" in code

    def test_health_endpoint_is_db_free(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/api/v1/endpoints/health.py").read_text(encoding="utf-8")
        code = _code_only(text)
        assert "HealthService" not in code
        assert "PublicUnitOfWork" not in code
        assert "liveness_probe" in code


# -- Text strippers -----------------------------------------------------------


class TestPyprojectStrip:
    def test_db_deps_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "pyproject.toml").read_text(encoding="utf-8")
        for dep in ("sqlalchemy", "asyncpg", "alembic", "psycopg"):
            assert dep not in text.lower(), f"{dep!r} should be stripped from pyproject.toml"

    def test_non_db_deps_preserved(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "pyproject.toml").read_text(encoding="utf-8")
        assert "fastapi" in text
        assert "pydantic" in text
        assert "uvicorn" in text


class TestEnvExampleStrip:
    def test_db_env_vars_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / ".env.example").read_text(encoding="utf-8")
        assert "APP__DB__URL" not in text
        assert "APP__DB__POOL_SIZE" not in text
        assert "DATABASE_URL" not in text

    def test_non_db_env_vars_preserved(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / ".env.example").read_text(encoding="utf-8")
        assert "APP__APP__TITLE" in text
        assert "APP__SERVER__PORT" in text


class TestApiRouterStrip:
    def test_items_tasks_imports_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/api/v1/api.py").read_text(encoding="utf-8")
        assert "items" not in text.split("from app.api.v1.endpoints import")[-1].split("\n")[0]
        assert "tasks" not in text.split("from app.api.v1.endpoints import")[-1].split("\n")[0]

    def test_items_tasks_include_router_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/api/v1/api.py").read_text(encoding="utf-8")
        assert "items.router" not in text
        assert "tasks.router" not in text

    def test_remaining_routes_kept(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/api/v1/api.py").read_text(encoding="utf-8")
        assert "home.router" in text
        assert "health.router" in text
        assert "admin.router" in text


class TestYamlAndDomainStrip:
    def test_default_yaml_db_block_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "config/default.yaml").read_text(encoding="utf-8")
        assert "\ndb:" not in text
        assert text.startswith("app:") or "app:" in text
        assert "server:" in text  # other blocks kept

    def test_dbconfig_class_removed(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/core/config/domain.py").read_text(encoding="utf-8")
        assert "class DbConfig" not in text
        assert "class AppConfig" in text  # siblings preserved
        assert "db: DbConfig" not in text


class TestCliInitStrip:
    """Cluster C1 — cli/__init__.py must lose the ``app.cli.db`` references
    after the stripper runs. Without this, ``python -m app`` fails at first
    import with ``ModuleNotFoundError: No module named 'app.cli.db'`` because
    cli/db.py was already deleted by _PYTHON_DB_TARGETS.
    """

    def test_db_import_dropped(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/cli/__init__.py").read_text(encoding="utf-8")
        assert "from app.cli.db import db_app" not in text

    def test_db_typer_registration_dropped(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/cli/__init__.py").read_text(encoding="utf-8")
        assert "cli.add_typer(db_app" not in text

    def test_non_db_cli_surface_preserved(self, python_backend: Path):
        strip_python_database(python_backend)
        text = (python_backend / "src/app/cli/__init__.py").read_text(encoding="utf-8")
        # server sub-command must survive so the runtime entrypoint still works.
        assert "from app.cli.server import server_app" in text
        assert "cli.add_typer(server_app" in text


class TestLoaderQualifiedFieldStrip:
    """Cluster C2 — _strip_loader_db_refs must also strip the qualified
    Settings field ``db: domain.DbConfig = domain.DbConfig()`` that the
    production loader.py declares. The existing import-only regex misses it
    because production loader.py imports via ``from . import domain, sources``
    (no direct ``DbConfig`` name to match), so the qualified field reference
    survives the strip and crashes at module load with AttributeError.
    """

    def test_qualified_db_field_stripped(self, tmp_path: Path):
        # Faithful production loader.py layout (the python_backend fixture's
        # loader.py uses a different import shape — direct DbConfig import —
        # which the existing regex already handles; this is the unhandled case).
        backend = tmp_path / "api"
        backend.mkdir()
        _write(
            backend / "src/app/core/config/loader.py",
            "from . import domain, sources\n"
            "\n"
            "class Settings:\n"
            "    db: domain.DbConfig = domain.DbConfig()\n"
            "    server: domain.ServerConfig = domain.ServerConfig()\n",
        )
        # Minimal scaffolding so strip_python_database doesn't bail.
        _write(backend / "src/app/cli/__init__.py", "import typer\n")
        _write(backend / "pyproject.toml", "[project]\ndependencies = []\n")

        strip_python_database(backend)

        text = (backend / "src/app/core/config/loader.py").read_text(encoding="utf-8")
        assert "domain.DbConfig" not in text, "qualified DbConfig field must be stripped"
        assert "db:" not in text, "db: field declaration must be removed"
        # Sibling fields preserved.
        assert "domain.ServerConfig" in text


class TestProvenanceHook:
    """Cluster D — strip_python_database keeps the provenance manifest
    consistent with the post-strip state on disk: drops records for deleted
    DB targets, re-records stripper-rewritten files with their new hash.

    Required so the generator can run the stripper BEFORE fragment
    application: with the manifest correctly stamped as base-template, any
    fragment that subsequently injects into lifecycle.py (default
    ``middleware.pii_redaction`` does exactly this) becomes the manifest
    owner with the correct final hash — no FR1 violation, no silent
    security regression.
    """

    def test_records_lifecycle_with_base_template_origin(
        self, python_backend: Path
    ):
        from forge.sync.provenance import ProvenanceCollector

        # python_backend is at <tmp_path>/api. collector's project_root must
        # be at or above backend_dir for relative_to() to succeed.
        project_root = python_backend.parent
        collector = ProvenanceCollector(project_root=project_root)
        # Pre-seed the collector with the pre-strip lifecycle hash so we
        # can verify the strip refreshes (not just appends).
        collector.record(
            python_backend / "src/app/core/lifecycle.py",
            origin="base-template",
        )
        pre_strip_hash = collector.records["api/src/app/core/lifecycle.py"].sha256

        strip_python_database(
            python_backend,
            collector=collector,
            template_name="services/python-service-template",
            template_version="1.0.0",
        )

        post = collector.records["api/src/app/core/lifecycle.py"]
        assert post.origin == "base-template"
        assert post.template_name == "services/python-service-template"
        assert post.template_version == "1.0.0"
        # Hash MUST have changed — stateless replacement is a different file.
        assert post.sha256 != pre_strip_hash

    def test_drops_records_for_deleted_db_targets(self, python_backend: Path):
        from forge.sync.provenance import ProvenanceCollector

        project_root = python_backend.parent
        collector = ProvenanceCollector(project_root=project_root)
        # Seed with records the stripper will need to drop.
        for rel in (
            "api/alembic/versions/0001_initial.py",
            "api/alembic.ini",
            "api/src/app/data/models/item.py",
            "api/src/app/cli/db.py",
        ):
            (project_root / rel).parent.mkdir(parents=True, exist_ok=True)
            (project_root / rel).write_text("x")
            collector.record(project_root / rel, origin="base-template")

        strip_python_database(python_backend, collector=collector)

        # Every deleted-target row must be gone.
        for key in (
            "api/alembic/versions/0001_initial.py",
            "api/alembic.ini",
            "api/src/app/data/models/item.py",
            "api/src/app/cli/db.py",
        ):
            assert key not in collector.records, f"{key} should be pruned"

    def test_no_collector_is_a_no_op(self, python_backend: Path):
        """Existing callers that don't pass a collector must keep working."""
        strip_python_database(python_backend)  # no-collector path
        assert (python_backend / "src/app/core/lifecycle.py").is_file()


class TestIdempotence:
    """Running the stripper a second time on the same tree must be a no-op."""

    def test_double_strip_does_not_raise(self, python_backend: Path):
        strip_python_database(python_backend)
        strip_python_database(python_backend)  # no raise

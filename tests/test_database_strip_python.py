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


class TestIdempotence:
    """Running the stripper a second time on the same tree must be a no-op."""

    def test_double_strip_does_not_raise(self, python_backend: Path):
        strip_python_database(python_backend)
        strip_python_database(python_backend)  # no raise

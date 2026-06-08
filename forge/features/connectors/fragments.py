"""Connectors fragment — registers a per-service ConnectorRegistry.

The connector framework (Connector ABC, ConnectorRegistry, SyncRunner,
config/secrets split, and the HTTP / Filesystem / Sample / S3 / SQL
builtins) is vendored into the generated project under
``src/app/connectors/`` and imports only the stdlib + pydantic / httpx /
sqlalchemy from the base template — no private SDKs.

The fragment reads ``connectors.backends`` at render time to pre-enable
the selected builtins in ``build_connector_registry()``. The S3 builtin
needs ``boto3`` and the SQL builtin needs an async driver (aiosqlite
ships in the base; install ``asyncpg`` for Postgres); both are
import-guarded so an un-installed backend is skipped rather than crashing
boot. Backend selection lives in the generated ``app/connectors/`` tree
and can be edited post-generate.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="connectors_registry",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("connectors_registry", "python"),
                    # No private-SDK dep: the vendored framework needs only
                    # pydantic / httpx / sqlalchemy, all base-template deps.
                    # boto3 (s3) + asyncpg (postgres sql) are optional and
                    # import-guarded in app.connectors.builtin.
                    reads_options=("connectors.backends",),
                ),
            },
        )
    )

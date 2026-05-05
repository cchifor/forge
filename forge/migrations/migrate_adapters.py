"""Codemod: restructure legacy RAG fragments into ports/adapters.

Phase 2.3 moves each integration behind a port. Projects generated with
pre-1.0 forge have, for example, ``src/app/rag/qdrant_client.py`` —
post-migration this should live as ``src/app/adapters/vector_store/qdrant.py``
with the port at ``src/app/ports/vector_store.py``.

This codemod:

  1. Creates the ``ports/`` and ``adapters/`` directories.
  2. Suggests moves for any files matching the legacy path.
  3. Does NOT rewrite imports — user code that references
     ``app.rag.qdrant_client`` must be updated manually. The migration
     report lists every site that needs edits (found by grep).

Full rewriting requires AST-level Python refactoring (tokenize +
libcst), which lands with Phase 2.3's 1.0.0a3 expansion. For 1.0.0a1,
the codemod surfaces the work that needs to happen rather than doing
it silently.
"""

from __future__ import annotations

from pathlib import Path

from forge.migrations.base import MigrationReport

NAME = "adapters"
FROM = "0.x"
TO = "1.0.0a1"
DESCRIPTION = "Suggest ports/adapters restructure for legacy RAG fragments."


def run(project_root: Path, dry_run: bool = False, quiet: bool = False) -> MigrationReport:
    report = MigrationReport(name=NAME, applied=False)

    for backend_dir in (
        (project_root / "services").glob("*") if (project_root / "services").is_dir() else []
    ):
        rag_dir = backend_dir / "src" / "app" / "rag"
        if not rag_dir.is_dir():
            continue
        ports_dir = backend_dir / "src" / "app" / "ports"
        adapters_dir = backend_dir / "src" / "app" / "adapters" / "vector_store"
        if dry_run:
            report.changes.append(
                f"would propose: {backend_dir.name}/src/app/ports/vector_store.py"
            )
            report.changes.append(
                f"would propose: {backend_dir.name}/src/app/adapters/vector_store/*.py"
            )
            continue
        ports_dir.mkdir(parents=True, exist_ok=True)
        adapters_dir.mkdir(parents=True, exist_ok=True)

        port_hint = ports_dir / "vector_store.py.suggested"
        if not port_hint.exists():
            port_hint.write_text(_SUGGESTED_PORT, encoding="utf-8")
            report.changes.append(
                f"suggested: {port_hint.relative_to(project_root)} "
                "(Protocol for vector-store adapters — rename to .py to adopt)"
            )

    if not report.changes:
        report.skipped_reason = "no legacy rag/ directories found"
    else:
        report.applied = not dry_run
    return report


_SUGGESTED_PORT = '''\
"""Vector-store port — migrate from pre-1.0 rag/ module.

See `docs/architecture-decisions/ADR-002-ports-and-adapters.md` for the
pattern. After adopting this port, the concrete implementation lives
under `adapters/vector_store/<provider>.py` and is registered with the
dependency container by its env var.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class VectorHit:
    id: str
    score: float
    text: str
    metadata: dict[str, Any]


class VectorStorePort(Protocol):
    async def upsert(
        self,
        *,
        tenant_id: str,
        vectors: list[tuple[str, list[float], str, dict[str, Any]]],
    ) -> None: ...

    async def query(
        self,
        *,
        tenant_id: str,
        embedding: list[float],
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorHit]: ...

    async def delete(self, *, tenant_id: str, ids: list[str]) -> None: ...

    async def ensure_collection(self, *, tenant_id: str, dim: int) -> None: ...
'''

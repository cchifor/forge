"""Rewrite a generated project's alembic migrations into a valid linear chain.

Each fragment ships its migration with a hard-coded ``revision`` /
``down_revision`` (``0002``, ``0003``, ``0005`` …) that assumes a specific
fragment set. Any *subset* therefore produces a broken history: collisions
(``conversation_persistence`` and ``rag_pipeline`` both ship ``0003``) and
gaps (``webhooks`` is ``0005`` with ``down_revision="0004"`` but nothing ships
``0004``). Alembic rejects both, so ``alembic upgrade head`` crashes and the
service never boots.

After generation we renumber the migrations actually present into one linear
history. The order is deterministic (numeric prefix, then filename), so a
re-generation with an unchanged fragment set rewrites to identical IDs (no-op
diff). This rewrites revision IDs, so it is safe for ``forge new``; for
``forge --update`` of a *deployed* project, adding a data-model fragment can
shift later revision IDs — a known limitation tracked separately.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_NUMERIC_PREFIX = re.compile(r"^(\d+)_")
_REV_LINE = re.compile(r'^(revision\s*(?::[^=\n]+)?=\s*)("[^"]*"|None)(.*)$', re.M)
_DOWN_LINE = re.compile(r'^(down_revision\s*(?::[^=\n]+)?=\s*)("[^"]*"|None)(.*)$', re.M)


def _sort_key(path: Path) -> tuple[int, int, str]:
    """Order migrations: numeric-prefixed first (by number), then the rest
    (e.g. ``domain_*`` codegen migrations) stably by name. The base
    ``0001_initial`` therefore stays the root."""
    m = _NUMERIC_PREFIX.match(path.name)
    if m:
        return (0, int(m.group(1)), path.name)
    return (1, 0, path.name)


def rechain_migrations(versions_dir: Path) -> list[Path]:
    """Renumber the migrations in ``versions_dir`` into one valid linear chain.

    Returns the migration files it modified (so callers can refresh their
    provenance SHA). A no-op when the directory is missing or holds no
    migration files.
    """
    if not versions_dir.is_dir():
        return []
    candidates = sorted(
        (p for p in versions_dir.glob("*.py") if not p.name.startswith("__")),
        key=_sort_key,
    )

    def _is_rewritable(text: str) -> bool:
        # Require BOTH a revision and a down_revision we can rewrite. A file
        # whose down_revision uses an unsupported shape (tuple merge, multiline)
        # is skipped wholesale rather than half-rewritten (stale down_revision).
        return bool(_REV_LINE.search(text) and _DOWN_LINE.search(text))

    migrations = [
        p for p in candidates if _is_rewritable(p.read_text(encoding="utf-8"))
    ]
    modified: list[Path] = []
    prev: str | None = None
    for i, path in enumerate(migrations):
        new_rev = f"{i + 1:04d}"
        text = path.read_text(encoding="utf-8")
        new_text = _REV_LINE.sub(rf'\g<1>"{new_rev}"\g<3>', text, count=1)
        down_value = f'"{prev}"' if prev is not None else "None"
        new_text = _DOWN_LINE.sub(rf"\g<1>{down_value}\g<3>", new_text, count=1)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            modified.append(path)
        prev = new_rev
    return modified


def rechain_backend_migrations(config: Any, project_root: Path, collector: Any) -> None:
    """Rechain every Python backend's alembic migrations and refresh provenance.

    Shared by ``forge.generator`` (fresh ``forge new``) and the ``forge --update``
    path: both write the fragments' hard-coded (colliding/gapped) revisions, so
    both must renumber afterwards. The provenance SHA is refreshed for each
    rewritten file so ``forge.toml`` matches on disk — without this, the next
    ``--update`` would see "fragment changed, user didn't" and overwrite the
    rechained file with the broken original.
    """
    from dataclasses import replace  # noqa: PLC0415

    from forge.config import BackendLanguage  # noqa: PLC0415
    from forge.sync.provenance import sha256_of  # noqa: PLC0415

    for bc in config.backends:
        if bc.language is not BackendLanguage.PYTHON:
            continue
        versions = project_root / "services" / bc.name / "alembic" / "versions"
        for path in rechain_migrations(versions):
            key = path.relative_to(project_root).as_posix()
            rec = collector.records.get(key)
            if rec is not None:
                collector.records[key] = replace(rec, sha256=sha256_of(path))

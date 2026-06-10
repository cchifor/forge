"""The entrypoint promised a Postgres advisory lock around migrations so
concurrent replicas serialize; for a long time no such lock existed. These
assert the lock is real (and the comment matches it)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_ENV = _ROOT / "forge/templates/services/python-service-template/template/alembic/env.py"
_ENTRY = _ROOT / "forge/templates/services/python-service-template/template/entrypoint.sh.jinja"


def test_env_takes_advisory_lock_on_postgres():
    src = _ENV.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in src
    # Scoped to postgres so SQLite dev paths still work.
    assert 'connection.dialect.name == "postgresql"' in src
    # Acquired inside the migration transaction (xact lock auto-releases).
    body = src.split("def do_run_migrations")[1]
    assert body.index("begin_transaction") < body.index("pg_advisory_xact_lock")


def test_entrypoint_comment_matches_reality():
    src = _ENTRY.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in src, "comment must describe the real lock"

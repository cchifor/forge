"""Regression: Rust backend boots without a live DB (audit #24).

``db::create_pool`` used ``PgPoolOptions::new().connect(&url).await.expect(...)``
— an EAGER connect that panics under ``#[tokio::main]`` when the database is
unreachable at boot, exiting the process (CrashLoopBackOff in-cluster; non-zero
exit under docker-compose if started before Postgres). Python (lazy engine +
health 503) and Node (lazy Prisma + 503) sit Running-but-NotReady and self-heal
— Rust was the outlier.

Fix: ``connect_lazy`` validates the URL but doesn't open a connection at boot;
the first query connects, and ``/health/ready`` (``SELECT 1``) surfaces DB-down
as 503 so the pod self-heals once Postgres is reachable.
"""

from __future__ import annotations

from pathlib import Path

_RUST = (
    Path(__file__).resolve().parent.parent
    / "forge/templates/services/rust-service-template/template/src"
)


def test_create_pool_is_lazy() -> None:
    db_rs = (_RUST / "db.rs").read_text(encoding="utf-8")
    assert "connect_lazy" in db_rs, (
        "rust create_pool must use connect_lazy so an unreachable DB at boot "
        "doesn't panic the process (CrashLoopBackOff)"
    )
    assert ".connect(&url)" not in db_rs, (
        "rust create_pool must not eagerly connect at boot"
    )


def test_readiness_still_pings_db() -> None:
    # The lazy pool relies on /health/ready actually probing the DB to surface
    # DB-down as 503 (graceful, matching Python/Node).
    health = (_RUST / "routes/health.rs").read_text(encoding="utf-8")
    assert "SELECT 1" in health

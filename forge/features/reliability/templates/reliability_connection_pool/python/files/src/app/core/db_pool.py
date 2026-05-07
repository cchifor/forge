"""Sane SQLAlchemy async pool defaults for production.

Overrides the default ``QueuePool`` configuration so the generated
service handles burst traffic without blocking on pool-exhausted
connection waits.

Defaults:
  * ``pool_size=20``        — steady-state concurrent connections
  * ``max_overflow=10``     — burst capacity
  * ``pool_pre_ping=True``  — verify the connection is live before use
  * ``pool_recycle=1800``   — recycle connections every 30 minutes

All tunable via env vars so operators can dial them per-environment
without rebuilding:

    SQLALCHEMY_POOL_SIZE=20
    SQLALCHEMY_MAX_OVERFLOW=10
    SQLALCHEMY_POOL_RECYCLE=1800
"""

from __future__ import annotations

import os
from typing import Any

_TRUE_STRINGS = frozenset({"1", "true", "yes", "on"})


def pool_kwargs() -> dict[str, Any]:
    """Return the keyword arguments to pass to ``create_async_engine(...)``.

    Import and use from ``core/db.py``::

        from app.core.db_pool import pool_kwargs
        engine = create_async_engine(url, **pool_kwargs())
    """
    return {
        "pool_size": int(os.getenv("SQLALCHEMY_POOL_SIZE", "20")),
        "max_overflow": int(os.getenv("SQLALCHEMY_MAX_OVERFLOW", "10")),
        "pool_pre_ping": os.getenv("SQLALCHEMY_POOL_PRE_PING", "true").lower()
        in _TRUE_STRINGS,
        "pool_recycle": int(os.getenv("SQLALCHEMY_POOL_RECYCLE", "1800")),
    }

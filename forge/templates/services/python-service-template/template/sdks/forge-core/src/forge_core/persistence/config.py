"""Engine-argument assembly for :class:`~forge_core.persistence.database.AsyncDatabase`.

Pure functions that translate a small, declarative pool/connection config into
the keyword arguments SQLAlchemy's ``create_async_engine`` expects, with the
dialect-specific quirks (SQLite's thread guard, asyncpg's ``server_settings``
nesting, the ``ssl`` vs ``sslmode`` connect-arg key) handled in one place.
"""

from __future__ import annotations

import json
from typing import Any


def build_engine_args(
    url: str,
    *,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = -1,
    echo: bool = False,
    application_name: str | None = None,
    ssl_mode: str | None = None,
    connect_args: dict[str, Any] | None = None,
    is_async: bool = False,
) -> dict[str, Any]:
    """Build the kwargs for ``create_async_engine`` / ``create_engine``.

    Pooling args are only emitted for non-SQLite URLs (SQLite uses an
    in-process pool and rejects them). ``application_name`` and ``ssl_mode``
    are routed into the right ``connect_args`` slot for the driver in use.
    JSON (de)serialization is pinned to the stdlib ``json`` module so JSON
    columns round-trip identically across dialects.
    """
    connect_args = connect_args.copy() if connect_args else {}

    engine_args: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": True,
    }

    if "sqlite" in url:
        connect_args["check_same_thread"] = False
    else:
        engine_args.update(
            {
                "pool_size": pool_size,
                "max_overflow": max_overflow,
                "pool_timeout": pool_timeout,
                "pool_recycle": pool_recycle,
            }
        )
        if application_name:
            if is_async and "asyncpg" in url:
                connect_args.setdefault("server_settings", {})
                connect_args["server_settings"]["application_name"] = application_name
            else:
                connect_args["application_name"] = application_name

        if ssl_mode:
            key = "ssl" if (is_async or "asyncpg" in url) else "sslmode"
            connect_args[key] = ssl_mode

    if connect_args:
        engine_args["connect_args"] = connect_args

    engine_args["json_serializer"] = json.dumps
    engine_args["json_deserializer"] = json.loads

    return engine_args


def obfuscate_url(url: str) -> str:
    """Strip credentials from a DB URL for safe logging (``...@host/db``)."""
    if "@" in url:
        return f"...@{url.split('@', 1)[1]}"
    return url

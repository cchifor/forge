import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def build_engine_args(
    url: str,
    pool_size: int,
    max_overflow: int,
    pool_timeout: int,
    pool_recycle: int,
    echo: bool,
    application_name: str | None,
    ssl_mode: str | None,
    connect_args: dict[str, Any] | None,
    is_async: bool = False,
) -> dict[str, Any]:
    connect_args = connect_args.copy() if connect_args else {}

    engine_args: dict[str, Any] = {
        "echo": echo,
        "pool_pre_ping": True,
    }

    if "sqlite" in url:
        connect_args.update({"check_same_thread": False})
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
                if "server_settings" not in connect_args:
                    connect_args["server_settings"] = {}
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
    if "@" in url:
        return f"...@{url.split('@', 1)[1]}"
    return url

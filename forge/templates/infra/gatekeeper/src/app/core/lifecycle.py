# src/app/core/lifecycle.py
"""
Lightweight application lifecycle — no DI container, no discovery, no DB.
"""

import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class AppLifecycle:
    """
    Orchestrates the Application Lifecycle.
    """

    @classmethod
    def bootstrap(cls, app: FastAPI, config: Settings) -> None:
        """Configure logging and perform one-time wiring."""
        cls._setup_logging(config)
        logger.info("Bootstrapping %s v%s …", config.app.title, config.app.version)
        logger.info("Application bootstrap complete.")

    @classmethod
    @asynccontextmanager
    async def lifespan(cls, _app: FastAPI) -> AsyncGenerator[None]:
        """ASGI lifespan context manager."""
        from app.gatekeeper.http_client import close_http_client, init_http_client
        from app.gatekeeper.redis import ResilientRedis, close_redis, init_redis

        logger.info("Server starting up…")
        await init_http_client()
        client = await init_redis()
        if isinstance(client, ResilientRedis):
            logger.info("Active storage backend: %s", client.backend_name)
        yield
        await close_redis()
        await close_http_client()
        logger.info("Shutdown complete. Goodbye.")

    @staticmethod
    def _setup_logging(config: Settings) -> None:
        """Configure logging from YAML-derived settings."""
        if not hasattr(config, "logging"):
            return

        try:
            logging_dict = config.logging.model_dump(by_alias=True, exclude_unset=True)
            logging_dict["disable_existing_loggers"] = False
            logging.config.dictConfig(logging_dict)
            logger.debug("Logging configuration applied.")
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            logging.error("Failed to apply logging config: %s", e)

    @staticmethod
    def settings() -> Settings:
        """Get or create settings instance (for CLI usage)."""
        from app.core.config import get_settings

        return get_settings()

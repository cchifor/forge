import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.core.config import Settings
from app.core.ioc import ALL_PROVIDERS
from service.discovery import Discovery
from service.security import auth
from service.tasks.runner import BackgroundTaskRunner

logger = logging.getLogger(__name__)


class AppLifecycle:
    """Orchestrates the Application Lifecycle.
    Separates 'Build-time' wiring (Bootstrap) from 'Run-time' management (Lifespan).
    """

    _task_runner: BackgroundTaskRunner | None = None

    @classmethod
    def bootstrap(cls, app: FastAPI, config: Settings) -> None:
        """PHASE 1: BUILD-TIME CONFIGURATION"""

        # 1. Configure Logging
        cls._setup_logging(config)
        logger.info(f"Bootstrapping {config.app.title} v{config.app.version}...")

        # 2. Setup Dependency Injection (Dishka)
        providers = [P() for P in ALL_PROVIDERS]
        container = make_async_container(*providers, context={Settings: config})
        setup_dishka(container, app)

        # 3. Setup Authentication
        if config.security.auth.enabled:
            from service.security.providers.keycloak import KeycloakProvider

            provider = KeycloakProvider(config.security.auth)
        else:
            from service.security.providers.dev import DevAuthProvider

            provider = DevAuthProvider(config.security.auth)
            logger.warning("Auth DISABLED — using DevAuthProvider (dev mode only)")

        auth.initialize_auth(
            app,
            provider=provider,
            auth_url=config.security.auth.auth_url,
            token_url=config.security.auth.token_url,
        )

        logger.info("Application bootstrap complete. Waiting for server startup...")

    @classmethod
    @asynccontextmanager
    async def lifespan(cls, app: FastAPI) -> AsyncGenerator[None]:
        """PHASE 2: RUNTIME LIFECYCLE"""

        container: AsyncContainer | None = getattr(app.state, "dishka_container", None)
        if not container:
            raise RuntimeError(
                "DI Container not found in app.state. "
                "Did you forget to call AppLifecycle.bootstrap(app, config)?"
            )

        try:
            logger.info("Server starting up...")

            await cls._on_startup(container)
            config = await container.get(Settings)

            logger.info("Startup tasks complete.")
            logger.info(
                f"Listening on {config.server.host}:{config.server.port}, (Press CTRL+C to quit)"
            )
            logger.info("Server is ready to accept requests.")
            yield

        except Exception as exc:
            logger.critical(f"Critical Startup Failure: {exc}", exc_info=True)
            raise

        finally:
            logger.warning("Shutdown signal received. Initiating teardown...")
            await cls._on_shutdown(container)
            logger.info("Shutdown complete. Goodbye.")

    @staticmethod
    async def _on_startup(container: AsyncContainer) -> None:
        config = await container.get(Settings)

        if config.discovery.enabled:
            discovery_service = await container.get(Discovery)
            logger.info(f"Service registered: {discovery_service}")
        else:
            logger.info("Service discovery disabled, skipping registration.")

        # Auto-create tables for SQLite dev databases
        from service.db.aio import AsyncDatabase

        db = await container.get(AsyncDatabase)
        if "sqlite" in config.db.url:
            from app.data.models import Base

            async with db.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite tables auto-created (dev mode).")

        # Start background task runner
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        session_factory = await container.get(async_sessionmaker[AsyncSession])
        runner = BackgroundTaskRunner(session_factory, poll_interval=5.0)
        AppLifecycle._task_runner = runner
        await runner.start()
        logger.info("Background task runner started.")

    @staticmethod
    async def _on_shutdown(container: AsyncContainer) -> None:
        # Stop background task runner first (drains in-flight)
        if AppLifecycle._task_runner:
            await AppLifecycle._task_runner.stop()
            AppLifecycle._task_runner = None

        await container.close()
        logger.info("DI Container closed.")

    @staticmethod
    def _setup_logging(config: Settings) -> None:
        if not hasattr(config, "logging"):
            return
        try:
            logging_dict = config.logging.model_dump(by_alias=True, exclude_unset=True)
            logging_dict["disable_existing_loggers"] = False
            logging.config.dictConfig(logging_dict)
            logger.debug("Logging configuration applied.")
        except Exception as e:
            logging.basicConfig(level=logging.INFO)
            logging.error(f"Failed to apply logging config: {e}")
        # FORGE:LIFECYCLE_STARTUP

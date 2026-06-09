import logging
import logging.config
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from dishka import AsyncContainer, make_async_container
from dishka.integrations.fastapi import setup_dishka
from fastapi import FastAPI

from app.core.config import Settings
from app.core.ioc import ALL_PROVIDERS
from app.events.outbox import OutboxRelay
from forge_core.discovery import Discovery
from forge_core.security import auth
from forge_core.security.platform_auth_setup import build_auth_guard, issuer_url
from forge_core.security.trust import TenantTrust

logger = logging.getLogger(__name__)


class AppLifecycle:
    """Orchestrates the Application Lifecycle.
    Separates 'Build-time' wiring (Bootstrap) from 'Run-time' management (Lifespan).
    """

    _outbox_relay: OutboxRelay | None = None

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

        # 3. Setup Authentication. TMS is the cross-tenant control plane —
        # it never has a "tenant of its own"; the trust map below carries
        # only the operator/admin tenant for routes that consume bearer
        # tokens (e.g. tenant-management ops). Production wiring will
        # replace this in-memory map with one seeded from the tenant
        # routing tables. ``build_auth_guard`` is a module-level symbol an
        # auth provider can rebind (FORGE:APP_POST_CONFIGURE) to swap the
        # issuer wiring.
        bundle = build_auth_guard(config.security.auth)
        # Single-tenant local default: register the tenant the dev User is
        # bound to so the trust map answers consistently in dev /
        # single-tenant deployments. Production wiring overrides via a
        # TMS-backed CachingIssuerTrustMap. ``issuer_url`` returns the
        # configured issuer base URL — the only trusted issuer.
        try:
            from uuid import UUID

            bundle.trust_map.set(
                UUID("00000000-0000-0000-0000-000000000001"),
                TenantTrust(expected_issuer=issuer_url(config.security.auth)),
            )
        except (ValueError, AttributeError) as exc:
            logger.warning("default tenant trust seed skipped: %s", exc)

        if not config.security.auth.enabled:
            logger.warning("Auth DISABLED — dev mode (synthetic user, no JWT verification)")

        auth.initialize_auth(
            app,
            bundle=bundle,
            auth_url=config.security.auth.auth_url,
            token_url=config.security.auth.token_url,
            dev_mode=not config.security.auth.enabled,
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
        from forge_core.persistence import AsyncDatabase

        db = await container.get(AsyncDatabase)
        if "sqlite" in config.db.url:
            from app.data.models import Base

            async with db.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("SQLite tables auto-created (dev mode).")

        # Publish the session factory for code that runs outside request
        # scope (Taskiq workers, admin panel startup) — one engine, one
        # pool. The async_work feature's background_tasks fragment opts
        # into this when enabled.
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

        from app.core.db import set_session_factory

        session_factory = await container.get(async_sessionmaker[AsyncSession])
        set_session_factory(session_factory)

        # Start the outbox relay — publishes queued domain events to
        # Valkey Streams via the transactional-outbox pattern.
        relay = OutboxRelay(
            session_factory=session_factory,
            redis_url=config.tms.redis_url,
            poll_interval=2.0,
        )
        AppLifecycle._outbox_relay = relay
        await relay.start()
        logger.info("Outbox relay started.")
        # FORGE:LIFESPAN_STARTUP

    @staticmethod
    async def _on_shutdown(container: AsyncContainer) -> None:
        # Stop the outbox relay first so no in-flight publishes race the
        # container teardown.
        if AppLifecycle._outbox_relay:
            await AppLifecycle._outbox_relay.stop()
            AppLifecycle._outbox_relay = None
        # FORGE:LIFESPAN_SHUTDOWN
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

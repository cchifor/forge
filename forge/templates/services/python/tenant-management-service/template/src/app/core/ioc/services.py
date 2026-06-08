"""Application-service providers."""

from __future__ import annotations

from collections.abc import AsyncIterable

from dishka import Provider, Scope, provide

from app.core.config import Settings
from app.core.ioc.security import AuthUnitOfWork
from app.services.health_service import HealthService
from app.services.item_service import ItemService
from app.services.keycloak_admin import KeycloakAdminClient
from app.services.realm_service import RealmService
from app.services.redis_publisher import RedisPublisher
from app.services.tenant_service import TenantService


class ServiceProvider(Provider):
    """Domain / application services."""

    scope = Scope.APP

    @provide
    def get_health_service(self) -> HealthService:
        return HealthService()

    @provide(scope=Scope.REQUEST)
    def get_item_service(self, auth_uow: AuthUnitOfWork) -> ItemService:
        return ItemService(uow=auth_uow)

    # ── TMS services ──────────────────────────────────────────────────

    @provide
    async def get_keycloak_admin(self, settings: Settings) -> AsyncIterable[KeycloakAdminClient]:
        client = KeycloakAdminClient(
            base_url=settings.tms.keycloak_admin_url,
            admin_user=settings.tms.keycloak_admin_user,
            admin_password=settings.tms.keycloak_admin_password,
        )
        yield client
        await client.close()

    @provide
    async def get_redis_publisher(self, settings: Settings) -> AsyncIterable[RedisPublisher]:
        pub = RedisPublisher(redis_url=settings.tms.redis_url)
        yield pub
        await pub.close()

    @provide(scope=Scope.REQUEST)
    def get_realm_service(self, auth_uow: AuthUnitOfWork) -> RealmService:
        return RealmService(uow=auth_uow)

    @provide(scope=Scope.REQUEST)
    def get_tenant_service(
        self,
        auth_uow: AuthUnitOfWork,
        keycloak: KeycloakAdminClient,
        redis_pub: RedisPublisher,
        settings: Settings,
    ) -> TenantService:
        return TenantService(
            uow=auth_uow,
            keycloak=keycloak,
            redis_pub=redis_pub,
            gatekeeper_client_id=settings.tms.default_gatekeeper_client_id,
        )

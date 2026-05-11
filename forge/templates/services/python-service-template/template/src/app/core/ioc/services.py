"""Application-service providers."""

from __future__ import annotations

from dishka import Provider, Scope, provide

from app.core.ioc.security import AuthUnitOfWork
from app.services.health_service import HealthService
from app.services.item_service import ItemService


class ServiceProvider(Provider):
    """Domain / application services."""

    scope = Scope.APP

    @provide
    def get_health_service(self) -> HealthService:
        return HealthService()

    @provide(scope=Scope.REQUEST)
    def get_item_service(self, auth_uow: AuthUnitOfWork) -> ItemService:
        return ItemService(uow=auth_uow)

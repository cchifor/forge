"""Security providers: authentication, unit-of-work scoping."""

from __future__ import annotations

from typing import NewType

from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from service.core import context
from service.domain.account import Account
from service.domain.user import User
from service.security.auth import authenticate_request
from service.uow.aio import AsyncUnitOfWork

AuthUnitOfWork = NewType("AuthUnitOfWork", AsyncUnitOfWork)
PublicUnitOfWork = NewType("PublicUnitOfWork", AsyncUnitOfWork)


class SecurityProvider(Provider):
    """User authentication and tenant-scoped unit-of-work."""

    scope = Scope.APP

    @provide(scope=Scope.REQUEST)
    async def get_current_user(self, request: Request) -> User:
        user = await authenticate_request(request)
        if not user:
            raise HTTPException(status_code=401, detail="Authentication required for this resource")
        context.set_context(customer_id=user.customer_id, user_id=user.id)
        return user

    @provide(scope=Scope.REQUEST)
    def get_auth_uow(
        self, session_factory: async_sessionmaker[AsyncSession], user: User
    ) -> AuthUnitOfWork:
        account = Account(customer_id=user.customer_id, user_id=user.id)
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        return AuthUnitOfWork(uow)

    @provide(scope=Scope.REQUEST)
    def get_public_uow(self, session_factory: async_sessionmaker[AsyncSession]) -> PublicUnitOfWork:
        uow = AsyncUnitOfWork(session_factory=session_factory, account=None)
        return PublicUnitOfWork(uow)

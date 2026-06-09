"""Security providers: authentication, unit-of-work scoping."""

from __future__ import annotations

from typing import NewType

from dishka import Provider, Scope, provide
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from forge_core.domain import context
from forge_core.domain.account import Account
from forge_core.domain.user import User
from forge_core.persistence import AsyncUnitOfWork
from forge_core.security.auth import authenticate_request

AuthUnitOfWork = NewType("AuthUnitOfWork", AsyncUnitOfWork)
PublicUnitOfWork = NewType("PublicUnitOfWork", AsyncUnitOfWork)

# Optional per-session binder for DB-layer tenant isolation that needs more than
# the default RLS GUC — e.g. schema-per-tenant routes ``search_path`` from the
# authenticated account. ``None`` in the base (inert); a multitenancy fragment
# installs one below the marker. The binder is invoked on every UoW
# ``__aenter__`` with the account (possibly ``None``) and must fail closed.
_SESSION_BINDER = None
# FORGE:UOW_SESSION_BINDER


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
        uow = AsyncUnitOfWork(
            session_factory=session_factory, account=account, session_binder=_SESSION_BINDER
        )
        return AuthUnitOfWork(uow)

    @provide(scope=Scope.REQUEST)
    def get_public_uow(self, session_factory: async_sessionmaker[AsyncSession]) -> PublicUnitOfWork:
        # No account → the binder (if any) fails closed (e.g. empty search_path).
        uow = AsyncUnitOfWork(
            session_factory=session_factory, account=None, session_binder=_SESSION_BINDER
        )
        return PublicUnitOfWork(uow)

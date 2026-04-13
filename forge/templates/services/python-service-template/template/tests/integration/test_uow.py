"""Integration tests for service.uow.aio."""

import pytest
from sqlalchemy import text

from app.data.models.item import ItemModel
from app.domain.item import Item
from service.domain.account import Account
from service.uow.aio import AsyncUnitOfWork, HealthRepository


class TestAsyncUnitOfWork:
    @pytest.fixture
    def account(self):
        return Account(
            customer_id="00000000-0000-0000-0000-000000000001",
            user_id="00000000-0000-0000-0000-000000000001",
        )

    async def test_context_manager_commit(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        async with uow:
            uow.session.add(ItemModel(
                name="test-item", customer_id=account.customer_id,
                user_id=account.user_id,
            ))
        # Verify committed
        async with session_factory() as s:
            result = await s.execute(text("SELECT count(*) FROM items"))
            assert result.scalar() >= 1

    async def test_context_manager_rollback(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        with pytest.raises(ValueError):
            async with uow:
                uow.session.add(ItemModel(
                    name="rollback-item", customer_id=account.customer_id,
                    user_id=account.user_id,
                ))
                raise ValueError("trigger rollback")

    def test_session_not_active_raises(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        with pytest.raises(RuntimeError, match="not active"):
            _ = uow.session

    async def test_repo_caching(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        async with uow:
            repo1 = uow.repo(ItemModel, Item)
            repo2 = uow.repo(ItemModel, Item)
            assert repo1 is repo2

    async def test_repo_custom_class(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        async with uow:
            repo = uow.repo(HealthRepository)
            assert isinstance(repo, HealthRepository)

    async def test_repo_invalid_args_raises(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        async with uow:
            with pytest.raises((ValueError, TypeError)):
                uow.repo(str)  # type: ignore

    async def test_manual_flush(self, session_factory, account):
        uow = AsyncUnitOfWork(session_factory=session_factory, account=account)
        async with uow:
            uow.session.add(ItemModel(
                name="flush-item", customer_id=account.customer_id,
                user_id=account.user_id,
            ))
            await uow.flush()


class TestHealthRepository:
    async def test_ping_db_success(self, session_factory):
        async with session_factory() as session:
            repo = HealthRepository(session)
            assert await repo.ping_db() is True

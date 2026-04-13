"""Unit tests for ItemRepository with in-memory SQLite."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.data.models import Base
from app.data.repositories.item_repository import ItemRepository
from app.domain.item import ItemCreate, ItemStatus
from service.domain.account import Account


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
def session_factory(engine):
    return async_sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        class_=AsyncSession,
    )


@pytest.fixture
async def session(session_factory):
    async with session_factory() as s:
        yield s


@pytest.fixture
def account():
    return Account(
        customer_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )


@pytest.fixture
def repo(session, account):
    return ItemRepository(session=session, account=account)


# ── Helpers ─────────────────────────────────────────────────────


async def _create_item(repo, name="Test", status=ItemStatus.DRAFT):
    return await repo.create(
        ItemCreate(name=name, status=status)
    )


# ── Tests ───────────────────────────────────────────────────────


class TestListItems:
    async def test_list_returns_all(self, repo):
        await _create_item(repo, "A")
        await _create_item(repo, "B")
        items = await repo.list_items()
        assert len(items) == 2

    async def test_search_by_name(self, repo):
        await _create_item(repo, "Alpha Widget")
        await _create_item(repo, "Beta Gadget")
        items = await repo.list_items(search="alpha")
        assert len(items) == 1
        assert items[0].name == "Alpha Widget"

    async def test_search_no_match(self, repo):
        await _create_item(repo, "Something")
        items = await repo.list_items(search="zzz_none")
        assert len(items) == 0

    async def test_filter_by_status(self, repo):
        await _create_item(repo, "Draft", ItemStatus.DRAFT)
        await _create_item(repo, "Active", ItemStatus.ACTIVE)
        items = await repo.list_items(status=ItemStatus.ACTIVE)
        assert len(items) == 1
        assert items[0].name == "Active"

    async def test_pagination(self, repo):
        for i in range(5):
            await _create_item(repo, f"Item{i}")
        page = await repo.list_items(skip=0, limit=2)
        assert len(page) == 2


class TestCountItems:
    async def test_count_all(self, repo):
        await _create_item(repo, "X")
        await _create_item(repo, "Y")
        assert await repo.count_items() == 2

    async def test_count_with_status_filter(self, repo):
        await _create_item(repo, "D", ItemStatus.DRAFT)
        await _create_item(repo, "A", ItemStatus.ACTIVE)
        count = await repo.count_items(status=ItemStatus.ACTIVE)
        assert count == 1


class TestNameExists:
    async def test_name_exists_true(self, repo):
        await _create_item(repo, "Unique")
        assert await repo.name_exists("Unique") is True

    async def test_name_exists_false(self, repo):
        assert await repo.name_exists("NoSuchName") is False

    async def test_name_exists_excludes_id(self, repo):
        created = await _create_item(repo, "ExcludeMe")
        # Same name but excluding its own id should be False
        assert await repo.name_exists(
            "ExcludeMe", exclude_id=created.id
        ) is False

"""Integration tests for ItemRepository using the real DB fixtures."""

from __future__ import annotations

import pytest

from app.data.repositories.item_repository import ItemRepository
from app.domain.item import ItemCreate, ItemStatus


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def repo(session_factory, test_account):
    """ItemRepository backed by the in-memory integration DB."""

    async def _make():
        session = session_factory()
        return ItemRepository(
            session=session, account=test_account
        ), session

    return _make


@pytest.fixture
async def item_repo(repo):
    r, session = await repo()
    yield r
    await session.close()


# ── Helpers ─────────────────────────────────────────────────────


async def _create(repo, name="Item", status=ItemStatus.DRAFT):
    return await repo.create(
        ItemCreate(name=name, status=status)
    )


# ── Tests ───────────────────────────────────────────────────────


class TestCreateAndGet:
    async def test_create_persists(self, item_repo):
        item = await _create(item_repo, "Persisted")
        assert item.name == "Persisted"
        assert item.id is not None

    async def test_get_returns_created(self, item_repo):
        created = await _create(item_repo, "Fetch Me")
        fetched = await item_repo.get(created.id)
        assert fetched is not None
        assert fetched.name == "Fetch Me"


class TestListItems:
    async def test_list_all(self, item_repo):
        await _create(item_repo, "A")
        await _create(item_repo, "B")
        items = await item_repo.list_items()
        assert len(items) == 2

    async def test_text_search(self, item_repo):
        await _create(item_repo, "Red Widget")
        await _create(item_repo, "Blue Gadget")
        results = await item_repo.list_items(search="widget")
        assert len(results) == 1
        assert results[0].name == "Red Widget"

    async def test_status_filter(self, item_repo):
        await _create(
            item_repo, "Draft", ItemStatus.DRAFT
        )
        await _create(
            item_repo, "Active", ItemStatus.ACTIVE
        )
        results = await item_repo.list_items(
            status=ItemStatus.ACTIVE
        )
        assert len(results) == 1
        assert results[0].status == ItemStatus.ACTIVE

    async def test_pagination(self, item_repo):
        for i in range(4):
            await _create(item_repo, f"P{i}")
        page = await item_repo.list_items(skip=0, limit=2)
        assert len(page) == 2
        page2 = await item_repo.list_items(skip=2, limit=2)
        assert len(page2) == 2


class TestCountItems:
    async def test_count_all(self, item_repo):
        await _create(item_repo, "C1")
        await _create(item_repo, "C2")
        await _create(item_repo, "C3")
        assert await item_repo.count_items() == 3

    async def test_count_with_status(self, item_repo):
        await _create(item_repo, "D", ItemStatus.DRAFT)
        await _create(item_repo, "A1", ItemStatus.ACTIVE)
        await _create(item_repo, "A2", ItemStatus.ACTIVE)
        count = await item_repo.count_items(
            status=ItemStatus.ACTIVE
        )
        assert count == 2


class TestNameExists:
    async def test_exists_true(self, item_repo):
        await _create(item_repo, "UniqueItem")
        assert await item_repo.name_exists("UniqueItem") is True

    async def test_exists_false(self, item_repo):
        assert (
            await item_repo.name_exists("NonExistent") is False
        )

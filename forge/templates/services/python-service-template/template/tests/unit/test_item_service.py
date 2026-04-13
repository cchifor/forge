"""Unit tests for ItemService with mocked UoW."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.errors import AlreadyExistsError, NotFoundError
from app.domain.item import Item, ItemCreate, ItemStatus, ItemUpdate
from app.services.item_service import ItemService


def _make_item(**overrides) -> Item:
    defaults = {
        "id": uuid4(),
        "name": "Test Item",
        "description": "A test item",
        "tags": ["test"],
        "status": ItemStatus.DRAFT,
        "customer_id": uuid4(),
        "user_id": uuid4(),
    }
    defaults.update(overrides)
    return Item(**defaults)


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.list_items = AsyncMock(return_value=[])
    repo.count_items = AsyncMock(return_value=0)
    repo.get = AsyncMock(return_value=None)
    repo.create = AsyncMock()
    repo.update = AsyncMock()
    repo.delete = AsyncMock()
    repo.name_exists = AsyncMock(return_value=False)
    return repo


@pytest.fixture
def service(async_uow_mock, mock_repo):
    async_uow_mock.repo = MagicMock(return_value=mock_repo)
    return ItemService(uow=async_uow_mock)


class TestListItems:
    async def test_list_empty(self, service, mock_repo):
        result = await service.list()
        assert result.total == 0
        assert result.items == []
        assert result.has_more is False

    async def test_list_with_items(self, service, mock_repo):
        items = [_make_item(name=f"Item {i}") for i in range(3)]
        mock_repo.list_items.return_value = items
        mock_repo.count_items.return_value = 3

        result = await service.list(skip=0, limit=50)
        assert result.total == 3
        assert len(result.items) == 3
        assert result.has_more is False

    async def test_list_with_pagination(self, service, mock_repo):
        items = [_make_item(name=f"Item {i}") for i in range(2)]
        mock_repo.list_items.return_value = items
        mock_repo.count_items.return_value = 5

        result = await service.list(skip=0, limit=2)
        assert result.total == 5
        assert len(result.items) == 2
        assert result.has_more is True


class TestGetItem:
    async def test_get_existing(self, service, mock_repo):
        item = _make_item()
        mock_repo.get.return_value = item

        result = await service.get(item.id)
        assert result.id == item.id

    async def test_get_not_found(self, service, mock_repo):
        mock_repo.get.return_value = None
        with pytest.raises(NotFoundError):
            await service.get(uuid4())


class TestCreateItem:
    async def test_create_success(self, service, mock_repo):
        item = _make_item(name="New Item")
        mock_repo.create.return_value = item

        result = await service.create(ItemCreate(name="New Item"))
        assert result.name == "New Item"

    async def test_create_duplicate_name(self, service, mock_repo):
        mock_repo.name_exists.return_value = True
        with pytest.raises(AlreadyExistsError):
            await service.create(ItemCreate(name="Duplicate"))


class TestUpdateItem:
    async def test_update_success(self, service, mock_repo):
        existing = _make_item(name="Old Name")
        updated = _make_item(name="New Name", id=existing.id)
        mock_repo.get.return_value = existing
        mock_repo.update.return_value = updated

        result = await service.update(existing.id, ItemUpdate(name="New Name"))
        assert result.name == "New Name"

    async def test_update_not_found(self, service, mock_repo):
        mock_repo.get.return_value = None
        with pytest.raises(NotFoundError):
            await service.update(uuid4(), ItemUpdate(name="X"))


class TestDeleteItem:
    async def test_delete_success(self, service, mock_repo):
        item = _make_item()
        mock_repo.get.return_value = item
        await service.delete(item.id)
        mock_repo.delete.assert_awaited_once_with(item.id)

    async def test_delete_not_found(self, service, mock_repo):
        mock_repo.get.return_value = None
        with pytest.raises(NotFoundError):
            await service.delete(uuid4())

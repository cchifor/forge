"""Test item repository against real PostgreSQL."""

import uuid

import pytest
from sqlalchemy import select

from app.data.models.item import ItemModel

pytestmark = pytest.mark.docker

TEST_CUSTOMER = uuid.uuid4()
TEST_USER = uuid.uuid4()


class TestItemRepositoryDocker:
    async def test_create_item(self, docker_session):
        """Create an item in real PostgreSQL."""
        item = ItemModel(
            id=uuid.uuid4(),
            name="Test Item",
            description="A test item",
            status="DRAFT",
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        assert item.id is not None
        assert item.name == "Test Item"

    async def test_query_items(self, docker_session):
        """Query items from real PostgreSQL."""
        item = ItemModel(
            id=uuid.uuid4(),
            name="Query Test",
            status="ACTIVE",
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        result = await docker_session.execute(
            select(ItemModel).where(ItemModel.name == "Query Test")
        )
        found = result.scalar_one()
        assert found.name == "Query Test"
        assert found.status == "ACTIVE"

    async def test_update_item(self, docker_session):
        """Update an item in real PostgreSQL."""
        item = ItemModel(
            id=uuid.uuid4(),
            name="Update Test",
            status="DRAFT",
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        item.status = "ACTIVE"
        await docker_session.flush()

        result = await docker_session.execute(
            select(ItemModel).where(ItemModel.id == item.id)
        )
        assert result.scalar_one().status == "ACTIVE"

    async def test_delete_item(self, docker_session):
        """Delete an item from real PostgreSQL."""
        item_id = uuid.uuid4()
        item = ItemModel(
            id=item_id,
            name="Delete Test",
            status="DRAFT",
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        await docker_session.delete(item)
        await docker_session.flush()

        result = await docker_session.execute(
            select(ItemModel).where(ItemModel.id == item_id)
        )
        assert result.scalar_one_or_none() is None

    async def test_uuid_primary_key(self, docker_session):
        """PostgreSQL UUID type works correctly."""
        item_id = uuid.uuid4()
        item = ItemModel(
            id=item_id,
            name="UUID Test",
            status="DRAFT",
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        result = await docker_session.execute(
            select(ItemModel).where(ItemModel.id == item_id)
        )
        assert result.scalar_one().id == item_id

    async def test_json_column(self, docker_session):
        """PostgreSQL JSON column works for tags."""
        item = ItemModel(
            id=uuid.uuid4(),
            name="JSON Test",
            status="DRAFT",
            tags=["red", "large", "premium"],
            customer_id=TEST_CUSTOMER,
            user_id=TEST_USER,
        )
        docker_session.add(item)
        await docker_session.flush()

        result = await docker_session.execute(
            select(ItemModel).where(ItemModel.name == "JSON Test")
        )
        found = result.scalar_one()
        assert "red" in found.tags
        assert len(found.tags) == 3

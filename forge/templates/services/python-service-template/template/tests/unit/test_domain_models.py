"""Tests for app-layer domain models (Pydantic schemas and enums)."""

from __future__ import annotations

import datetime
import platform
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.base import BaseDomainModel, PaginatedResponse
from app.domain.health import (
    ComponentStatus,
    HealthStatus,
    LivenessResponse,
    ReadinessResponse,
)
from app.domain.item import (
    Item,
    ItemCreate,
    ItemStatus,
    ItemSummary,
    ItemUpdate,
    PaginatedItemResponse,
)


# -- ItemStatus enum ----------------------------------------------------------


class TestItemStatus:
    def test_values(self):
        assert set(ItemStatus) == {
            ItemStatus.DRAFT,
            ItemStatus.ACTIVE,
            ItemStatus.ARCHIVED,
        }

    def test_str_enum_string_value(self):
        assert str(ItemStatus.DRAFT) == "DRAFT"
        assert ItemStatus.ACTIVE == "ACTIVE"


# -- ItemCreate ----------------------------------------------------------------


class TestItemCreate:
    def test_minimal(self):
        item = ItemCreate(name="widget")
        assert item.name == "widget"
        assert item.description is None
        assert item.tags == []
        assert item.status == ItemStatus.DRAFT

    def test_all_fields(self):
        item = ItemCreate(
            name="widget",
            description="A useful widget",
            tags=["a", "b"],
            status=ItemStatus.ACTIVE,
        )
        assert item.description == "A useful widget"
        assert item.tags == ["a", "b"]
        assert item.status == ItemStatus.ACTIVE

    def test_name_required(self):
        with pytest.raises(ValidationError):
            ItemCreate()

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            ItemCreate(name="")


# -- ItemUpdate ----------------------------------------------------------------


class TestItemUpdate:
    def test_all_optional(self):
        update = ItemUpdate()
        assert update.name is None
        assert update.description is None
        assert update.tags is None
        assert update.status is None


# -- Item (full domain model) --------------------------------------------------


class TestItem:
    def test_instantiation(self):
        uid = uuid4()
        cid = uuid4()
        tid = uuid4()
        item = Item(
            id=uid,
            name="thing",
            status=ItemStatus.ACTIVE,
            customer_id=cid,
            user_id=tid,
        )
        assert item.id == uid
        assert item.name == "thing"
        assert item.status == "ACTIVE"
        assert item.customer_id == cid

    def test_frozen(self):
        item = Item(
            id=uuid4(),
            name="x",
            status=ItemStatus.DRAFT,
            customer_id=uuid4(),
            user_id=uuid4(),
        )
        with pytest.raises(ValidationError):
            item.name = "y"

    def test_model_dump(self):
        uid = uuid4()
        item = Item(
            id=uid,
            name="x",
            status=ItemStatus.DRAFT,
            customer_id=uuid4(),
            user_id=uuid4(),
        )
        data = item.model_dump()
        assert data["id"] == uid
        assert data["status"] == "DRAFT"
        assert isinstance(data, dict)


# -- ItemSummary ---------------------------------------------------------------


class TestItemSummary:
    def test_defaults(self):
        summary = ItemSummary(
            id=uuid4(), name="s", status=ItemStatus.ARCHIVED
        )
        assert summary.tags == []
        assert summary.created_at is None


# -- PaginatedResponse ---------------------------------------------------------


class TestPaginatedResponse:
    def test_structure(self):
        resp = PaginatedResponse[str](
            items=["a", "b"], total=10, skip=0, limit=2, has_more=True
        )
        assert resp.items == ["a", "b"]
        assert resp.total == 10
        assert resp.has_more is True

    def test_paginated_item_alias(self):
        uid = uuid4()
        item = Item(
            id=uid,
            name="p",
            status=ItemStatus.DRAFT,
            customer_id=uuid4(),
            user_id=uuid4(),
        )
        resp = PaginatedItemResponse(
            items=[item], total=1, skip=0, limit=10, has_more=False
        )
        assert len(resp.items) == 1
        assert resp.items[0].id == uid


# -- HealthStatus enum ---------------------------------------------------------


class TestHealthStatus:
    def test_values(self):
        assert set(HealthStatus) == {
            HealthStatus.UP,
            HealthStatus.DOWN,
            HealthStatus.DEGRADED,
        }

    def test_string_value(self):
        assert HealthStatus.UP.value == "UP"


# -- LivenessResponse / ReadinessResponse -------------------------------------


class TestLivenessResponse:
    def test_defaults(self):
        resp = LivenessResponse()
        assert resp.status == HealthStatus.UP
        assert resp.details == "Service is running"

    def test_custom(self):
        resp = LivenessResponse(
            status=HealthStatus.DOWN, details="shutting down"
        )
        assert resp.status == HealthStatus.DOWN


class TestReadinessResponse:
    def test_with_components(self):
        comp = ComponentStatus(status=HealthStatus.UP, latency_ms=1.5)
        resp = ReadinessResponse(
            status=HealthStatus.UP, components={"db": comp}
        )
        assert resp.components["db"].latency_ms == 1.5

    def test_system_info_defaults(self):
        resp = ReadinessResponse(
            status=HealthStatus.UP, components={}
        )
        assert "python_version" in resp.system_info
        assert resp.system_info["python_version"] == platform.python_version()

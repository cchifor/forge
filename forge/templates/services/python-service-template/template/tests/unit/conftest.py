"""Unit test fixtures.

Unit tests should be fast, isolated, and not depend on external services.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest


@dataclass
class FakeUser:
    """Lightweight stand-in for an authenticated user."""

    id: str = "user-1"
    customer_id: str = "tenant-1"
    email: str = "test@example.com"
    roles: list[str] = field(default_factory=lambda: ["user"])


@pytest.fixture
def fake_user() -> FakeUser:
    return FakeUser()


@pytest.fixture
def fake_account():
    from service.domain.account import Account

    return Account(
        customer_id="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
    )


@pytest.fixture
def random_uuid() -> UUID:
    return uuid4()


@pytest.fixture
def async_uow_mock():
    """A mock AsyncUnitOfWork that supports ``async with``."""
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    return uow

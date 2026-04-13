"""Integration tests for service.db.aio.AsyncDatabase."""

import pytest

from service.db.aio import AsyncDatabase


class TestAsyncDatabase:
    async def test_init_sqlite(self):
        db = AsyncDatabase(url="sqlite+aiosqlite:///:memory:")
        try:
            assert db.engine is not None
            assert db.session_factory is not None
        finally:
            await db.dispose()

    async def test_check_connection_success(self):
        db = AsyncDatabase(url="sqlite+aiosqlite:///:memory:")
        try:
            assert await db.check_connection() is True
        finally:
            await db.dispose()

    async def test_dispose(self):
        db = AsyncDatabase(url="sqlite+aiosqlite:///:memory:")
        await db.dispose()
        # After dispose, engine should still be an object but disposed

    async def test_from_config(self):
        db = AsyncDatabase.from_config({"url": "sqlite+aiosqlite:///:memory:"})
        try:
            assert db.engine is not None
        finally:
            await db.dispose()

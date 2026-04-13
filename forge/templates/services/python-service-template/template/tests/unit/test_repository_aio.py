"""Unit tests for AsyncBaseRepository with in-memory SQLite."""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import String, Uuid
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from service.repository.aio import AsyncBaseRepository
from service.repository.base import MAX_PAGE_SIZE
from service.repository.errors import EntityNotFoundException


# ── Test model + schemas ────────────────────────────────────────


class _Base(DeclarativeBase):
    pass


class WidgetModel(_Base):
    __tablename__ = "widgets"
    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100))


class Widget(BaseModel):
    model_config = {"from_attributes": True}
    id: uuid.UUID
    name: str


class WidgetCreate(BaseModel):
    name: str


class WidgetUpdate(BaseModel):
    name: str | None = None


class WidgetRepo(
    AsyncBaseRepository[
        WidgetModel, Widget, WidgetCreate, WidgetUpdate
    ]
):
    def __init__(self, session: AsyncSession):
        super().__init__(
            session=session,
            model=WidgetModel,
            schema=Widget,
            account=None,
        )


# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False
    )
    async with eng.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
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
def repo(session):
    return WidgetRepo(session)


# ── Tests ───────────────────────────────────────────────────────


class TestCreate:
    async def test_create_returns_schema(self, repo):
        result = await repo.create(WidgetCreate(name="Alpha"))
        assert isinstance(result, Widget)
        assert result.name == "Alpha"

    async def test_create_assigns_id(self, repo):
        result = await repo.create(WidgetCreate(name="Beta"))
        assert result.id is not None


class TestGet:
    async def test_get_existing(self, repo):
        created = await repo.create(WidgetCreate(name="Gamma"))
        fetched = await repo.get(created.id)
        assert fetched is not None
        assert fetched.name == "Gamma"

    async def test_get_missing_returns_none(self, repo):
        result = await repo.get(uuid.uuid4())
        assert result is None


class TestGetOrFail:
    async def test_get_or_fail_success(self, repo):
        created = await repo.create(WidgetCreate(name="Delta"))
        result = await repo.get_or_fail(created.id)
        assert result.name == "Delta"

    async def test_get_or_fail_raises(self, repo):
        with pytest.raises(EntityNotFoundException):
            await repo.get_or_fail(uuid.uuid4())


class TestUpdate:
    async def test_update_changes_field(self, repo):
        created = await repo.create(WidgetCreate(name="Old"))
        updated = await repo.update(
            created.id, WidgetUpdate(name="New")
        )
        assert updated.name == "New"

    async def test_update_missing_raises(self, repo):
        with pytest.raises(EntityNotFoundException):
            await repo.update(
                uuid.uuid4(), WidgetUpdate(name="X")
            )


class TestDelete:
    async def test_delete_removes_entity(self, repo):
        created = await repo.create(WidgetCreate(name="Bye"))
        await repo.delete(created.id)
        assert await repo.get(created.id) is None

    async def test_delete_missing_raises(self, repo):
        with pytest.raises(EntityNotFoundException):
            await repo.delete(uuid.uuid4())


class TestCount:
    async def test_count_empty(self, repo):
        assert await repo.count() == 0

    async def test_count_after_inserts(self, repo):
        await repo.create(WidgetCreate(name="A"))
        await repo.create(WidgetCreate(name="B"))
        assert await repo.count() == 2


class TestExists:
    async def test_exists_true(self, repo):
        created = await repo.create(WidgetCreate(name="E"))
        assert await repo.exists(created.id) is True

    async def test_exists_false(self, repo):
        assert await repo.exists(uuid.uuid4()) is False


class TestGetAllPagination:
    async def test_get_all_with_limit(self, repo):
        for i in range(5):
            await repo.create(WidgetCreate(name=f"W{i}"))
        page = await repo.get_all(skip=0, limit=2)
        assert len(page) == 2

    async def test_get_all_skip(self, repo):
        for i in range(3):
            await repo.create(WidgetCreate(name=f"S{i}"))
        page = await repo.get_all(skip=2, limit=10)
        assert len(page) == 1

    async def test_max_page_size_clamped(self, repo):
        # limit > MAX_PAGE_SIZE should be clamped
        for i in range(3):
            await repo.create(WidgetCreate(name=f"C{i}"))
        page = await repo.get_all(skip=0, limit=MAX_PAGE_SIZE + 500)
        # Should still return results (clamped, not error)
        assert len(page) == 3

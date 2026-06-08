"""Branch coverage for the persistence internals: config arg-building, the
repository's query helpers / error paths, and the unit-of-work plumbing
(repo resolution + caching, commit / rollback / flush, the tenant-scoped
session helper). These complement ``test_persistence.py``'s behavioural
round-trip with the edge branches a happy-path test doesn't reach.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    selectinload,
)

from forge_core.errors import NotFoundError, RepositoryError
from forge_core.persistence import (
    AsyncBaseRepository,
    AsyncDatabase,
    AsyncUnitOfWork,
    build_engine_args,
    obfuscate_url,
    set_tenant_context,
    tenant_scoped_session,
)

pytestmark = pytest.mark.unit


# ── config.build_engine_args / obfuscate_url ────────────────────────


class TestBuildEngineArgs:
    def test_sqlite_sets_thread_guard_no_pool(self):
        args = build_engine_args("sqlite+aiosqlite:///x.db")
        assert args["connect_args"]["check_same_thread"] is False
        assert "pool_size" not in args

    def test_postgres_emits_pool_args(self):
        args = build_engine_args("postgresql://h/db", pool_size=7, max_overflow=3)
        assert args["pool_size"] == 7
        assert args["max_overflow"] == 3

    def test_asyncpg_application_name_nests_in_server_settings(self):
        args = build_engine_args("postgresql+asyncpg://h/db", application_name="svc", is_async=True)
        assert args["connect_args"]["server_settings"]["application_name"] == "svc"

    def test_sync_application_name_is_flat(self):
        args = build_engine_args("postgresql://h/db", application_name="svc")
        assert args["connect_args"]["application_name"] == "svc"

    def test_ssl_mode_async_uses_ssl_key(self):
        args = build_engine_args("postgresql+asyncpg://h/db", ssl_mode="require", is_async=True)
        assert args["connect_args"]["ssl"] == "require"

    def test_ssl_mode_sync_uses_sslmode_key(self):
        args = build_engine_args("postgresql://h/db", ssl_mode="require")
        assert args["connect_args"]["sslmode"] == "require"

    def test_json_serializers_pinned(self):
        args = build_engine_args("sqlite:///x")
        assert callable(args["json_serializer"])
        assert callable(args["json_deserializer"])


class TestObfuscateUrl:
    def test_strips_credentials(self):
        assert obfuscate_url("postgresql://u:p@host/db") == "...@host/db"

    def test_passthrough_without_credentials(self):
        assert obfuscate_url("sqlite:///x.db") == "sqlite:///x.db"


# ── Models / schemas ────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(nullable=False)
    body: Mapped[str | None] = mapped_column(nullable=True)


class Composite(Base):
    __tablename__ = "composite"
    a: Mapped[int] = mapped_column(primary_key=True)
    b: Mapped[int] = mapped_column(primary_key=True)


class UniqueNote(Base):
    __tablename__ = "unique_notes"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(nullable=False)
    __table_args__ = (UniqueConstraint("slug", name="uq_unique_notes_slug"),)


class Parent(Base):
    __tablename__ = "parents"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(nullable=False)
    children: Mapped[list[Child]] = relationship(back_populates="parent")


class Child(Base):
    __tablename__ = "children"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("parents.id"))
    label: Mapped[str] = mapped_column(nullable=False)
    parent: Mapped[Parent] = relationship(back_populates="children")


class ChildSchema(BaseModel):
    id: int
    label: str


class ParentSchema(BaseModel):
    id: int
    name: str
    children: list[ChildSchema] = []


class ParentCreate(BaseModel):
    name: str


class ParentUpdate(BaseModel):
    name: str | None = None


class UniqueNoteSchema(BaseModel):
    id: int
    slug: str


class UniqueNoteCreate(BaseModel):
    slug: str


class UniqueNoteUpdate(BaseModel):
    slug: str | None = None


class NoteSchema(BaseModel):
    id: int
    title: str
    body: str | None = None


class NoteCreate(BaseModel):
    title: str
    body: str | None = None


class NoteUpdate(BaseModel):
    title: str | None = None
    body: str | None = None


class StrictNote(BaseModel):
    id: int
    title: int  # deliberately wrong type ⇒ validation failure on map


class CompositeSchema(BaseModel):
    a: int
    b: int


@pytest.fixture
async def db():
    database = AsyncDatabase("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.dispose()


@pytest.fixture
async def session(db):
    async with db.session_factory() as s:
        yield s


def _notes(session, schema=NoteSchema):
    return AsyncBaseRepository(session=session, model=Note, schema=schema, account=None)


# ── Repository edge branches ────────────────────────────────────────


class TestRepositoryEdges:
    async def test_hard_delete_when_no_soft_delete_mixin(self, session):
        repo = _notes(session)
        created = await repo.create(NoteCreate(title="x"))
        await repo.delete(created.id)
        # No SoftDeleteMixin ⇒ row is physically gone.
        assert await repo.get(created.id) is None
        assert await repo.exists(created.id) is False

    async def test_get_by_no_match_returns_none(self, session):
        repo = _notes(session)
        assert await repo.get_by(title="absent") is None

    async def test_get_by_invalid_key_raises(self, session):
        repo = _notes(session)
        with pytest.raises(RepositoryError):
            await repo.get_by(bogus="x")

    async def test_sorting_descending_and_ascending(self, session):
        repo = _notes(session)
        await repo.create(NoteCreate(title="a"))
        await repo.create(NoteCreate(title="b"))
        await repo.create(NoteCreate(title="c"))
        asc_titles = [n.title for n in await repo.get_all(sort_by=["title"])]
        desc_titles = [n.title for n in await repo.get_all(sort_by=["-title"])]
        assert asc_titles == ["a", "b", "c"]
        assert desc_titles == ["c", "b", "a"]

    async def test_filtering_list_uses_in_clause(self, session):
        repo = _notes(session)
        await repo.create(NoteCreate(title="a"))
        await repo.create(NoteCreate(title="b"))
        await repo.create(NoteCreate(title="c"))
        rows = await repo.get_all(filters={"title": ["a", "c"]})
        assert {r.title for r in rows} == {"a", "c"}

    async def test_count_with_filter(self, session):
        repo = _notes(session)
        await repo.create(NoteCreate(title="a"))
        await repo.create(NoteCreate(title="a"))
        await repo.create(NoteCreate(title="b"))
        assert await repo.count(filters={"title": "a"}) == 2

    async def test_schema_validation_failure_maps_to_repository_error(self, session):
        # Insert via a valid schema, then read back through a mis-typed schema.
        _notes(session)  # create the table is already done in fixture
        good = _notes(session)
        created = await good.create(NoteCreate(title="hello"))
        bad = _notes(session, schema=StrictNote)
        with pytest.raises(RepositoryError):
            await bad.get(created.id)

    async def test_composite_pk_rejected(self, session):
        with pytest.raises(NotImplementedError):
            AsyncBaseRepository(
                session=session, model=Composite, schema=CompositeSchema, account=None
            )

    async def test_prepare_update_data_hook_is_called(self, session):
        seen: dict = {}

        class HookRepo(AsyncBaseRepository[Note, NoteSchema, NoteCreate, NoteUpdate]):
            def __init__(self, session, account=None):
                super().__init__(session=session, model=Note, schema=NoteSchema, account=account)

            def _prepare_update_data(self, db_obj, update_data):
                seen.update(update_data)
                return update_data

        repo = HookRepo(session)
        created = await repo.create(NoteCreate(title="x"))
        await repo.update(created.id, NoteUpdate(title="y"))
        assert seen == {"title": "y"}

    async def test_create_extra_kwarg_filtered_to_columns(self, session):
        repo = _notes(session)
        # ``not_a_column`` is dropped (only mapped columns survive).
        created = await repo.create(NoteCreate(title="x"), not_a_column="ignored")
        assert created.title == "x"

    async def test_create_unique_violation_maps_to_repository_error(self, session):
        repo = AsyncBaseRepository(
            session=session, model=UniqueNote, schema=UniqueNoteSchema, account=None
        )
        await repo.create(UniqueNoteCreate(slug="dup"))
        with pytest.raises(RepositoryError):
            await repo.create(UniqueNoteCreate(slug="dup"))

    async def test_update_unique_violation_maps_to_repository_error(self, session):
        repo = AsyncBaseRepository(
            session=session, model=UniqueNote, schema=UniqueNoteSchema, account=None
        )
        await repo.create(UniqueNoteCreate(slug="one"))
        two = await repo.create(UniqueNoteCreate(slug="two"))
        with pytest.raises(RepositoryError):
            await repo.update(two.id, UniqueNoteUpdate(slug="one"))

    async def test_orm_to_dict_traverses_loaded_relationships(self, session):
        parent_repo = AsyncBaseRepository(
            session=session, model=Parent, schema=ParentSchema, account=None
        )
        created = await parent_repo.create(ParentCreate(name="p"))
        session.add(Child(parent_id=created.id, label="c1"))
        session.add(Child(parent_id=created.id, label="c2"))
        await session.flush()
        # Eager-load the children so the relationship is present in state.dict
        # and _orm_to_dict's relationship branch runs.
        loaded = await parent_repo.get(created.id, options=[selectinload(Parent.children)])
        assert loaded is not None
        assert {c.label for c in loaded.children} == {"c1", "c2"}


# ── Unit-of-work plumbing ───────────────────────────────────────────


class TestUnitOfWorkResolution:
    async def test_generic_repo_is_cached(self, db):
        async with AsyncUnitOfWork(db.session_factory) as uow:
            r1 = uow.repo(Note, NoteSchema)
            r2 = uow.repo(Note, NoteSchema)
            assert r1 is r2

    async def test_custom_async_base_repo_subclass(self, db):
        class NoteRepo(AsyncBaseRepository[Note, NoteSchema, NoteCreate, NoteUpdate]):
            def __init__(self, session, account=None):
                super().__init__(session=session, model=Note, schema=NoteSchema, account=account)

        async with AsyncUnitOfWork(db.session_factory) as uow:
            r1 = uow.repo(NoteRepo)
            r2 = uow.repo(NoteRepo)
            assert r1 is r2 and isinstance(r1, NoteRepo)

    async def test_custom_plain_repo_gets_session_only(self, db):
        class PlainRepo:
            def __init__(self, session):
                self.session = session

        async with AsyncUnitOfWork(db.session_factory) as uow:
            r = uow.repo(PlainRepo)
            assert isinstance(r, PlainRepo)

    async def test_repo_invalid_args_raise(self, db):
        async with AsyncUnitOfWork(db.session_factory) as uow:
            with pytest.raises(ValueError):
                uow.repo("not-a-type")  # type: ignore[arg-type]

    async def test_session_outside_block_raises(self, db):
        uow = AsyncUnitOfWork(db.session_factory)
        with pytest.raises(RuntimeError):
            _ = uow.session

    async def test_collect_event_outside_block_raises(self, db):
        uow = AsyncUnitOfWork(db.session_factory, outbox_sink=lambda s, e: None)
        with pytest.raises(RuntimeError):
            uow.collect_event(object())

    async def test_explicit_commit_and_flush(self, db):
        async with AsyncUnitOfWork(db.session_factory) as uow:
            repo = uow.repo(Note, NoteSchema)
            await repo.create(NoteCreate(title="committed"))
            await uow.flush()
            await uow.commit()
        async with db.session_factory() as s:
            assert len(await _notes(s).get_all()) == 1

    async def test_explicit_rollback_discards(self, db):
        async with AsyncUnitOfWork(db.session_factory) as uow:
            repo = uow.repo(Note, NoteSchema)
            await repo.create(NoteCreate(title="rolled-back"))
            await uow.rollback()
        async with db.session_factory() as s:
            assert await _notes(s).get_all() == []

    async def test_exception_in_block_rolls_back(self, db):
        with pytest.raises(ValueError):
            async with AsyncUnitOfWork(db.session_factory) as uow:
                repo = uow.repo(Note, NoteSchema)
                await repo.create(NoteCreate(title="boom"))
                raise ValueError("boom")
        async with db.session_factory() as s:
            assert await _notes(s).get_all() == []


# ── RLS seam helpers (opt-in, no-op off Postgres) ───────────────────


class TestRlsSeamHelpers:
    async def test_tenant_scoped_session_yields_usable_session(self, db):
        tid = uuid.uuid4()
        async with tenant_scoped_session(db.session_factory, tid) as s:
            # On sqlite the GUC bind no-ops; the session is fully usable.
            repo = _notes(s)
            await repo.create(NoteCreate(title="scoped"))
            await s.commit()
        async with db.session_factory() as s:
            assert len(await _notes(s).get_all()) == 1

    async def test_set_tenant_context_custom_guc_noop_sqlite(self, session):
        await set_tenant_context(session, uuid.uuid4(), tenant_guc="my.guc")


class ChildWithParent(BaseModel):
    id: int
    label: str
    parent: ParentSchema | None = None


class TestRelationshipMapping:
    async def test_many_to_one_loaded_relationship(self, session):
        parent_repo = AsyncBaseRepository(
            session=session, model=Parent, schema=ParentSchema, account=None
        )
        p = await parent_repo.create(ParentCreate(name="mom"))
        session.add(Child(parent_id=p.id, label="kid"))
        await session.flush()
        child_repo = AsyncBaseRepository(
            session=session, model=Child, schema=ChildWithParent, account=None
        )
        loaded = await child_repo.get_all(options=[selectinload(Child.parent)])
        assert loaded[0].parent is not None
        assert loaded[0].parent.name == "mom"


class TestHealthRepositoryPing:
    async def test_ping_db_returns_false_on_error(self, db):
        from forge_core.persistence import HealthRepository

        class Boom:
            async def execute(self, *a, **k):
                raise RuntimeError("dead session")

            bind = None

        assert await HealthRepository(Boom()).ping_db() is False  # type: ignore[arg-type]


# ── NotFound is the forge error, not a bespoke one ──────────────────


class TestNotFoundIsForgeError:
    async def test_get_or_fail_uses_forge_not_found(self, session):
        repo = _notes(session)
        with pytest.raises(NotFoundError):
            await repo.get_or_fail(9999)

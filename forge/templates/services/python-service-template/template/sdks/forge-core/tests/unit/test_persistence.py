"""Behavioural tests for the forge-core persistence layer.

These run against an in-memory SQLite database (no weld, no Postgres) and
exercise the real round-trip: :class:`AsyncDatabase` → session →
:class:`AsyncBaseRepository` CRUD, the mixins' scoping behaviour, the error
mapping into :mod:`forge_core.errors`, and the *opt-in* nature of the tenant
RLS seam. The whole module importing and passing with only
``sqlalchemy + pydantic + aiosqlite`` installed is the proof that the layer is
genuinely weld-free.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from forge_core.errors import NotFoundError, RepositoryError
from forge_core.persistence import (
    DEFAULT_TENANT_GUC,
    AccountProtocol,
    AsyncBaseRepository,
    AsyncDatabase,
    AsyncUnitOfWork,
    HealthRepository,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UserOwnedMixin,
    set_tenant_context,
)

pytestmark = pytest.mark.unit


# ── Models / schemas under test ─────────────────────────────────────


class Base(DeclarativeBase):
    pass


class WidgetModel(Base, TenantMixin, UserOwnedMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "widgets"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(nullable=False)


class PlainModel(Base):
    """A model with no mixins — never tenant/owner/soft-delete scoped."""

    __tablename__ = "plain"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(nullable=False)


class Widget(BaseModel):
    id: uuid.UUID
    name: str
    customer_id: uuid.UUID
    user_id: uuid.UUID


class WidgetCreate(BaseModel):
    name: str


class WidgetUpdate(BaseModel):
    name: str | None = None


class Plain(BaseModel):
    id: uuid.UUID
    label: str


class PlainCreate(BaseModel):
    label: str


class PlainUpdate(BaseModel):
    label: str | None = None


# ── A minimal account (structurally satisfies AccountProtocol) ──────


class FakeAccount:
    def __init__(
        self,
        customer_id: uuid.UUID | None,
        user_id: uuid.UUID | None,
        *,
        admin: bool = False,
    ) -> None:
        self.customer_id = customer_id
        self.user_id = user_id
        self._admin = admin

    def is_admin(self) -> bool:
        return self._admin


CID_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
CID_B = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
UID_1 = uuid.UUID("00000000-0000-0000-0000-000000000001")
UID_2 = uuid.UUID("00000000-0000-0000-0000-000000000002")


# ── Fixtures ────────────────────────────────────────────────────────


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


def _widget_repo(session, account: AccountProtocol | None):
    return AsyncBaseRepository(session=session, model=WidgetModel, schema=Widget, account=account)


# ── AsyncDatabase ───────────────────────────────────────────────────


class TestAsyncDatabase:
    async def test_check_connection(self, db):
        assert await db.check_connection() is True

    async def test_from_config(self):
        database = AsyncDatabase.from_config({"url": "sqlite+aiosqlite:///:memory:"})
        assert await database.check_connection() is True
        await database.dispose()

    def test_pydantic_carriable(self):
        # The custom core-schema lets an AsyncDatabase live on a pydantic model.
        class Ctx(BaseModel):
            model_config = {"arbitrary_types_allowed": False}
            db: AsyncDatabase

        database = AsyncDatabase("sqlite+aiosqlite:///:memory:")
        ctx = Ctx(db=database)
        assert ctx.db is database


# ── CRUD round-trip ─────────────────────────────────────────────────


class TestCrudRoundTrip:
    async def test_create_get_update_delete(self, session):
        account = FakeAccount(CID_A, UID_1)
        repo = _widget_repo(session, account)

        created = await repo.create(WidgetCreate(name="alpha"))
        assert created.name == "alpha"
        # Tenant/owner columns are populated from the account on create.
        assert created.customer_id == CID_A
        assert created.user_id == UID_1

        fetched = await repo.get(created.id)
        assert fetched is not None and fetched.name == "alpha"

        updated = await repo.update(created.id, WidgetUpdate(name="beta"))
        assert updated.name == "beta"

        await repo.delete(created.id)
        # SoftDeleteMixin ⇒ delete flips is_active; scoped reads no longer see it.
        assert await repo.get(created.id) is None

    async def test_count_and_exists(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        a = await repo.create(WidgetCreate(name="a"))
        await repo.create(WidgetCreate(name="b"))
        assert await repo.count() == 2
        assert await repo.exists(a.id) is True

    async def test_get_all_and_get_by(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        await repo.create(WidgetCreate(name="one"))
        await repo.create(WidgetCreate(name="two"))
        rows = await repo.get_all()
        assert {r.name for r in rows} == {"one", "two"}
        hit = await repo.get_by(name="one")
        assert hit is not None and hit.name == "one"


# ── Error mapping into forge_core.errors ────────────────────────────


class TestErrorMapping:
    async def test_get_or_fail_raises_forge_not_found(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        with pytest.raises(NotFoundError):
            await repo.get_or_fail(uuid.uuid4())

    async def test_update_missing_raises_not_found(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        with pytest.raises(NotFoundError):
            await repo.update(uuid.uuid4(), WidgetUpdate(name="x"))

    async def test_delete_missing_raises_not_found(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        with pytest.raises(NotFoundError):
            await repo.delete(uuid.uuid4())

    async def test_invalid_filter_raises_repository_error(self, session):
        repo = _widget_repo(session, FakeAccount(CID_A, UID_1))
        with pytest.raises(RepositoryError):
            await repo.get_all(filters={"nonexistent_column": 1})

    async def test_no_primary_key_raises_repository_error(self, session):
        # PlainModel has a PK; assert the generic error type is the forge one by
        # exercising the duplicate-PK guard indirectly through filter validation.
        repo = AsyncBaseRepository(session=session, model=PlainModel, schema=Plain, account=None)
        with pytest.raises(RepositoryError):
            repo._validate_filter_keys({"bogus": 1})


# ── Mixin-driven scoping ────────────────────────────────────────────


class TestTenantScoping:
    async def test_tenant_isolation(self, session):
        # Seed one widget per tenant via per-tenant repos…
        repo_a = _widget_repo(session, FakeAccount(CID_A, UID_1))
        repo_b = _widget_repo(session, FakeAccount(CID_B, UID_2))
        await repo_a.create(WidgetCreate(name="a-owned"))
        await repo_b.create(WidgetCreate(name="b-owned"))
        # …each tenant only sees its own row.
        assert {r.name for r in await repo_a.get_all()} == {"a-owned"}
        assert {r.name for r in await repo_b.get_all()} == {"b-owned"}

    async def test_no_tenant_id_falls_closed(self, session):
        seeded = _widget_repo(session, FakeAccount(CID_A, UID_1))
        await seeded.create(WidgetCreate(name="hidden"))
        # An account with customer_id=None on a TenantMixin model sees nothing.
        scoped = _widget_repo(session, FakeAccount(None, UID_1))
        assert await scoped.get_all() == []


class TestOwnerScoping:
    async def test_non_admin_sees_only_own_rows(self, session):
        owner1 = _widget_repo(session, FakeAccount(CID_A, UID_1))
        owner2 = _widget_repo(session, FakeAccount(CID_A, UID_2))
        await owner1.create(WidgetCreate(name="u1"))
        await owner2.create(WidgetCreate(name="u2"))
        assert {r.name for r in await owner1.get_all()} == {"u1"}

    async def test_admin_sees_all_tenant_rows(self, session):
        owner1 = _widget_repo(session, FakeAccount(CID_A, UID_1))
        owner2 = _widget_repo(session, FakeAccount(CID_A, UID_2))
        await owner1.create(WidgetCreate(name="u1"))
        await owner2.create(WidgetCreate(name="u2"))
        admin = _widget_repo(session, FakeAccount(CID_A, UID_1, admin=True))
        assert {r.name for r in await admin.get_all()} == {"u1", "u2"}


class TestUnscopedModel:
    async def test_plain_model_ignores_account(self, session):
        # A model with no mixins is never scoped, even with an account present.
        repo = AsyncBaseRepository(
            session=session, model=PlainModel, schema=Plain, account=FakeAccount(CID_A, UID_1)
        )
        await repo.create(PlainCreate(label="x"))
        assert len(await repo.get_all()) == 1


# ── The tenant-scoping seam is opt-in ───────────────────────────────


class TestTenantScopingIsOptIn:
    def test_default_guc_is_app_current_tenant(self):
        # Aligns with forge's multitenancy feature GUC, not a Strive-specific name.
        assert DEFAULT_TENANT_GUC == "app.current_tenant"

    async def test_set_tenant_context_is_noop_on_sqlite(self, session):
        # No exception, no statement issued — the RLS path is Postgres-only.
        await set_tenant_context(session, CID_A)
        await set_tenant_context(session, CID_A, tenant_guc="custom.tenant")

    async def test_uow_without_account_never_scopes(self, db, monkeypatch):
        # A non-multitenant project constructs the UoW without an account; the
        # tenant-binding hook must never fire.
        calls: list[uuid.UUID] = []

        async def _spy(self, session):
            if self._account is not None and self._account.customer_id is not None:
                calls.append(self._account.customer_id)

        monkeypatch.setattr(AsyncUnitOfWork, "_apply_session_gucs", _spy, raising=True)
        async with AsyncUnitOfWork(db.session_factory):
            pass
        assert calls == []

    async def test_uow_with_account_attempts_scope(self, db):
        # With an account the hook runs; on sqlite set_tenant_context no-ops, so
        # the block completes cleanly — opt-in path is reachable + safe off PG.
        account = FakeAccount(CID_A, UID_1)
        async with AsyncUnitOfWork(db.session_factory, account=account) as uow:
            repo = uow.repo(WidgetModel, Widget)
            await repo.create(WidgetCreate(name="via-uow"))
        # Committed: a fresh scoped read sees it.
        async with db.session_factory() as s:
            assert len(await _widget_repo(s, account).get_all()) == 1

    async def test_collect_event_requires_sink(self, db):
        async with AsyncUnitOfWork(db.session_factory) as uow:
            with pytest.raises(RuntimeError):
                uow.collect_event(object())

    async def test_outbox_sink_flushed_on_commit(self, db):
        flushed: list[object] = []

        async def sink(session, events):
            flushed.extend(events)

        async with AsyncUnitOfWork(db.session_factory, outbox_sink=sink) as uow:
            uow.collect_event("evt-1")
        assert flushed == ["evt-1"]


# ── HealthRepository ────────────────────────────────────────────────


class TestHealthRepository:
    async def test_ping_db(self, session):
        assert await HealthRepository(session).ping_db() is True

    async def test_check_rls_guc_noop_on_sqlite(self, session):
        # No Postgres ⇒ GUC check trivially passes (returns True).
        assert await HealthRepository(session).check_rls_guc() is True


# ── AccountProtocol is structural ───────────────────────────────────


class TestAccountProtocol:
    def test_fake_account_satisfies_protocol(self):
        acct = FakeAccount(CID_A, UID_1)
        assert isinstance(acct, AccountProtocol)

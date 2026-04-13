"""Tests for SQLAlchemy ORM model metadata (table names, columns, indexes)."""

from __future__ import annotations

from sqlalchemy import inspect

from app.data.models.audit import AuditLog
from app.data.models.item import ItemModel


# -- ItemModel -----------------------------------------------------------------


class TestItemModel:
    def test_tablename(self):
        assert ItemModel.__tablename__ == "items"

    def test_primary_key(self):
        mapper = inspect(ItemModel)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["id"]

    def test_expected_columns(self):
        mapper = inspect(ItemModel)
        col_names = {c.key for c in mapper.column_attrs}
        expected = {
            "id",
            "name",
            "description",
            "tags",
            "status",
            "customer_id",
            "user_id",
            "created_at",
            "updated_at",
        }
        assert expected.issubset(col_names)

    def test_name_not_nullable(self):
        table = ItemModel.__table__
        assert table.c.name.nullable is False

    def test_description_nullable(self):
        table = ItemModel.__table__
        assert table.c.description.nullable is True

    def test_status_not_nullable(self):
        table = ItemModel.__table__
        assert table.c.status.nullable is False

    def test_customer_name_index_exists(self):
        table = ItemModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_items_customer_name" in index_names

    def test_customer_status_index_exists(self):
        table = ItemModel.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_items_customer_status" in index_names


# -- AuditLog ------------------------------------------------------------------


class TestAuditLog:
    def test_tablename(self):
        assert AuditLog.__tablename__ == "audit_logs"

    def test_primary_key(self):
        mapper = inspect(AuditLog)
        pk_cols = [c.name for c in mapper.primary_key]
        assert pk_cols == ["id"]

    def test_expected_columns(self):
        mapper = inspect(AuditLog)
        col_names = {c.key for c in mapper.column_attrs}
        for col in ("action", "entity_type", "entity_id", "username",
                     "ip_address", "status_code", "created_at"):
            assert col in col_names, f"missing column: {col}"

    def test_action_not_nullable(self):
        table = AuditLog.__table__
        assert table.c.action.nullable is False

    def test_nullable_columns(self):
        table = AuditLog.__table__
        for col_name in ("entity_type", "entity_id", "username",
                         "ip_address", "user_agent", "status_code",
                         "method", "path", "meta_data", "duration_ms"):
            assert table.c[col_name].nullable is True, (
                f"{col_name} should be nullable"
            )

    def test_customer_created_index(self):
        table = AuditLog.__table__
        index_names = {idx.name for idx in table.indexes}
        assert "ix_audit_customer_created" in index_names

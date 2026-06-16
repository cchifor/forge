"""Tests for the Pillar C.1 hardening of ``forge.domain.emitters``.

Covers the three concrete improvements:

1. Enum cross-reference validation — every emitter accepts a
   ``known_enums`` set; passing a spec that references an undefined enum
   raises :class:`UnknownEnumReferenceError`. Passing a spec whose enums
   all resolve is a no-op.
2. :func:`emit_alembic_migration` produces a syntactically valid Python
   module containing the expected ``op.create_table`` call shape.
3. :func:`emit_sqlalchemy_model` and :func:`emit_pydantic` are independent
   — emitting one does not require the other and they produce different
   surfaces.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from forge.domain import EntitySpec, load_entity_yaml
from forge.domain.emitters import (
    UnknownEnumReferenceError,
    emit_alembic_migration,
    emit_openapi,
    emit_pydantic,
    emit_rust_struct,
    emit_sqlalchemy_model,
    emit_zod,
    validate_enum_references,
)

SHIPPED_DOMAIN = Path(__file__).resolve().parent.parent / "forge" / "templates" / "_domain"


@pytest.fixture
def item_spec() -> EntitySpec:
    return load_entity_yaml(SHIPPED_DOMAIN / "items.yaml")


# ---------------------------------------------------------------------------
# Enum cross-reference validation
# ---------------------------------------------------------------------------


class TestValidateEnumReferences:
    def test_defined_enum_is_no_raise(self, item_spec: EntitySpec) -> None:
        # Item references ItemStatus; passing it in known_enums must succeed.
        validate_enum_references(item_spec, known_enums={"ItemStatus"})

    def test_undefined_enum_raises_typed_exception(self, item_spec: EntitySpec) -> None:
        # Item references ItemStatus; supplying a known-enums set that
        # *omits* ItemStatus must trip the validator.
        with pytest.raises(UnknownEnumReferenceError) as excinfo:
            validate_enum_references(item_spec, known_enums={"OtherStatus"})
        # The enum name must appear in the message — that's the whole
        # point of the typed error vs. a bare KeyError.
        assert "ItemStatus" in str(excinfo.value)
        assert excinfo.value.enum_name == "ItemStatus"
        assert excinfo.value.entity == "Item"
        assert excinfo.value.field == "status"

    def test_known_enums_none_skips_validation(self, item_spec: EntitySpec) -> None:
        # Backward compat: callers without an enum registry must not blow up.
        validate_enum_references(item_spec, known_enums=None)

    def test_spec_with_no_enum_fields_always_passes(self) -> None:
        from forge.domain import EntityField, FieldType

        spec = EntitySpec(
            name="Plain",
            plural="plains",
            description="",
            fields=(EntityField(name="id", type=FieldType.UUID, primary_key=True),),
        )
        # No enum fields means no references to validate.
        validate_enum_references(spec, known_enums=set())
        validate_enum_references(spec, known_enums={"Anything"})

    def test_error_message_lists_known_enums(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError) as excinfo:
            validate_enum_references(item_spec, known_enums={"FooStatus", "BarStatus"})
        # Sorted, comma-separated — helps the user spot a typo at a glance.
        assert "BarStatus" in str(excinfo.value)
        assert "FooStatus" in str(excinfo.value)

    def test_error_message_when_registry_empty(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError) as excinfo:
            validate_enum_references(item_spec, known_enums=set())
        assert "No enums are registered" in str(excinfo.value)


class TestEmittersRespectValidation:
    """Each public emit_* must surface the validation error itself, not
    silently emit broken code."""

    def test_emit_pydantic_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_pydantic(item_spec, known_enums={"Wrong"})

    def test_emit_sqlalchemy_model_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_sqlalchemy_model(item_spec, known_enums={"Wrong"})

    def test_emit_alembic_migration_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_alembic_migration(
                item_spec, revision="0002", down_revision="0001", known_enums={"Wrong"}
            )

    def test_emit_zod_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_zod(item_spec, known_enums={"Wrong"})

    def test_emit_rust_struct_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_rust_struct(item_spec, known_enums={"Wrong"})

    def test_emit_openapi_propagates(self, item_spec: EntitySpec) -> None:
        with pytest.raises(UnknownEnumReferenceError):
            emit_openapi(item_spec, known_enums={"Wrong"})


# ---------------------------------------------------------------------------
# emit_alembic_migration
# ---------------------------------------------------------------------------


class TestEmitAlembicMigration:
    def test_output_is_valid_python(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        # If ast.parse raises, the emitter produced broken Python.
        ast.parse(body)

    def test_output_has_revision_metadata(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert 'revision: str = "0002"' in body
        assert 'down_revision: Union[str, None] = "0001"' in body

    def test_first_migration_uses_none_down_revision(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0001", down_revision=None)
        assert "down_revision: Union[str, None] = None" in body

    def test_create_table_call_present(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert 'op.create_table(\n        "items",' in body

    def test_create_table_includes_each_column(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        for field in item_spec.fields:
            assert f'sa.Column("{field.name}",' in body

    def test_uuid_pk_column_uses_sa_uuid(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        # The id PK column uses sa.Uuid() with the gen_random_uuid() default,
        # matching the hand-written 0001_initial.py shape.
        assert 'sa.Column("id", sa.Uuid()' in body
        assert 'default=sa.text("gen_random_uuid()")' in body

    def test_string_column_with_max_length_emits_varchar(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        # name has max_length=255 → sa.String(255).
        assert 'sa.Column("name", sa.String(255)' in body

    def test_optional_field_is_nullable(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        # description is optional in items.yaml.
        assert 'sa.Column("description", sa.Text(), nullable=True)' in body

    def test_indexes_emitted_for_declared_indices(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert 'op.create_index("ix_items_customer_name", "items", ["customer_id", "name"])' in body
        assert (
            'op.create_index("ix_items_customer_status", "items", ["customer_id", "status"])'
            in body
        )

    def test_primary_key_constraint_emitted(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert 'sa.PrimaryKeyConstraint("id")' in body

    def test_downgrade_drops_table(self, item_spec: EntitySpec) -> None:
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert "def downgrade() -> None:" in body
        assert 'op.drop_table("items")' in body

    def test_enum_field_uses_string_column(self, item_spec: EntitySpec) -> None:
        # The 0001_initial template stores enums as VARCHAR rather than
        # native DB enums (native_enum=False on the ORM side). Mirror that.
        body = emit_alembic_migration(item_spec, revision="0002", down_revision="0001")
        assert 'sa.Column("status", sa.String(64)' in body
        assert 'server_default="DRAFT"' in body


# ---------------------------------------------------------------------------
# emit_sqlalchemy_model vs emit_pydantic — separate concerns
# ---------------------------------------------------------------------------


class TestSqlaPydanticIndependent:
    def test_sqla_model_is_valid_python(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        ast.parse(body)

    def test_pydantic_is_valid_python(self, item_spec: EntitySpec) -> None:
        body = emit_pydantic(item_spec)
        ast.parse(body)

    def test_sqla_emits_orm_class(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        assert "class ItemModel(Base):" in body
        assert '__tablename__ = "items"' in body
        assert "Mapped[" in body

    def test_pydantic_emits_basemodel(self, item_spec: EntitySpec) -> None:
        body = emit_pydantic(item_spec)
        assert "class Item(BaseModel):" in body
        # BaseModel comes from pydantic, not sqlalchemy — the DTO must not
        # leak ORM imports.
        assert "from sqlalchemy" not in body
        assert "Mapped[" not in body

    def test_sqla_does_not_leak_pydantic(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        # ORM must not import BaseModel — would create a cycle of concerns.
        assert "BaseModel" not in body
        assert "from pydantic" not in body

    def test_sqla_emits_indexes_under_table_args(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        assert "__table_args__" in body
        assert 'Index("ix_items_customer_name", "customer_id", "name")' in body
        assert 'Index("ix_items_customer_status", "customer_id", "status")' in body

    def test_sqla_uuid_pk_default(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        # The id column gets primary_key=True and uuid.uuid4 default.
        assert "primary_key=True" in body
        assert "default=uuid.uuid4" in body

    def test_sqla_enum_column_uses_app_enum_import(self, item_spec: EntitySpec) -> None:
        body = emit_sqlalchemy_model(item_spec)
        assert "from app.domain.enums import ItemStatus" in body
        assert "Enum(ItemStatus" in body
        assert "native_enum=False" in body

    def test_both_can_be_emitted_for_same_spec(self, item_spec: EntitySpec) -> None:
        # The key independence test: emitting one does not interfere with
        # emitting the other, and both succeed for the same spec without
        # any setup ordering.
        sqla = emit_sqlalchemy_model(item_spec, known_enums={"ItemStatus"})
        pyd = emit_pydantic(item_spec, known_enums={"ItemStatus"})
        assert "ItemModel" in sqla
        assert "class Item(BaseModel):" in pyd
        # Different surfaces — they share the entity name but nothing else.
        assert sqla != pyd


# ---------------------------------------------------------------------------
# emit_pydantic renders EntityField.default (parity with SQLA server_default)
# ---------------------------------------------------------------------------


class TestPydanticFieldDefault:
    """A field carrying a ``default`` must not emit as required.

    The same spec emits a SQLA ``server_default`` for the column; the
    Pydantic DTO must mirror that so the model is constructible without
    supplying the defaulted field. A bare ``status: str`` would force the
    caller to pass the value, diverging from the DB-side default.
    """

    def _spec(self) -> EntitySpec:
        from forge.domain import EntityField, FieldType

        return EntitySpec(
            name="Thing",
            plural="things",
            description="",
            fields=(
                EntityField(name="id", type=FieldType.UUID, primary_key=True),
                EntityField(name="status", type=FieldType.STRING, default="active"),
                EntityField(name="count", type=FieldType.INTEGER, default=0),
                EntityField(name="active", type=FieldType.BOOLEAN, default=True),
                EntityField(
                    name="label",
                    type=FieldType.STRING,
                    default="hi",
                    max_length=10,
                ),
            ),
        )

    def test_string_default_is_rendered(self) -> None:
        body = emit_pydantic(self._spec())
        # Must NOT be a bare required field.
        assert "    status: str\n" not in body
        assert 'status: str = "active"' in body

    def test_int_default_is_rendered(self) -> None:
        body = emit_pydantic(self._spec())
        assert "    count: int\n" not in body
        assert "count: int = 0" in body

    def test_bool_default_is_rendered(self) -> None:
        body = emit_pydantic(self._spec())
        assert "    active: bool\n" not in body
        assert "active: bool = True" in body

    def test_default_combined_with_constraint(self) -> None:
        body = emit_pydantic(self._spec())
        # When constraints force a Field(...), the default rides along.
        assert "label: str = Field(" in body
        assert 'default="hi"' in body
        assert "max_length=10" in body

    def test_output_remains_valid_python(self) -> None:
        body = emit_pydantic(self._spec())
        ast.parse(body)

    def test_string_default_with_quote_is_escaped(self) -> None:
        """A default containing a quote/backslash/newline must emit a
        valid, fully-escaped Python literal (repr-safe), not a naively
        double-quoted string that breaks the module."""
        from forge.domain import EntityField, FieldType

        spec = EntitySpec(
            name="Quoted",
            plural="quoteds",
            description="",
            fields=(
                EntityField(name="id", type=FieldType.UUID, primary_key=True),
                EntityField(
                    name="name",
                    type=FieldType.STRING,
                    default="O'Brien \"the\" \\hacker\nx",
                ),
            ),
        )
        body = emit_pydantic(spec)
        # The whole module must parse — a naive f'"{value}"' breaks here.
        module = ast.parse(body)
        # The emitted default literal must evaluate back to the original
        # string, proving the escaping is correct rather than merely parseable.
        assignments = {
            stmt.target.id: stmt.value
            for klass in module.body
            if isinstance(klass, ast.ClassDef)
            for stmt in klass.body
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
        }
        assert "name" in assignments
        assert ast.literal_eval(assignments["name"]) == "O'Brien \"the\" \\hacker\nx"

"""TMS schema: realms, tenants, outbox.

Adds the Tenant Management Service control-plane tables on top of the base
``0001`` revision (items + audit_logs + background_tasks). The TMS outbox
uses a service-specific shape (BIGINT autoincrement PK, payload TEXT, fixed
``ix_outbox_unpublished`` partial index) — not the generic events-outbox
shape — mirroring ``app.events`` + the ``realms`` / ``tenants`` ORM models.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "realms",
        sa.Column("id", sa.Uuid(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
        sa.Column("realm_type", sa.String(20), nullable=False, server_default="dedicated"),
        sa.Column("keycloak_base_url", sa.String(512), nullable=False),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("client_secret", sa.Text(), nullable=False),
        sa.Column("max_tenants", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_realms_name", "realms", ["name"])
    op.create_index("ix_realms_realm_type", "realms", ["realm_type"])

    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), nullable=False, default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(63), nullable=False, unique=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("hostname", sa.String(255), nullable=False, unique=True),
        sa.Column("admin_email", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False, server_default="free"),
        sa.Column("rate_limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "realm_id", sa.Uuid(), sa.ForeignKey("realms.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("keycloak_user_id", sa.String(255), nullable=True),
        sa.Column("provisioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_realm_id", "tenants", ["realm_id"])
    op.create_index("ix_tenants_status", "tenants", ["status"])
    op.create_index("ix_tenants_tier", "tenants", ["tier"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(32), nullable=False, unique=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("stream", sa.String(100), nullable=False, server_default="tms.events"),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox",
        ["published", "id"],
        postgresql_where=sa.text("published = false"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_unpublished", table_name="outbox")
    op.drop_table("outbox")
    op.drop_table("tenants")
    op.drop_table("realms")

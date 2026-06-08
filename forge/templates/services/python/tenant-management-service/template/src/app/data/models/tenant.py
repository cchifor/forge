# src/app/data/models/tenant.py
"""ORM model for tenants."""

from __future__ import annotations

import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.domain.tenant import TenantStatus, TenantTier
from forge_core.persistence import TimestampMixin


class TenantModel(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    admin_email: Mapped[str] = mapped_column(String(255), nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False, default=TenantTier.FREE)
    rate_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=TenantStatus.PENDING)
    realm_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("realms.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    keycloak_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provisioned_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # slug and hostname have unique=True which creates implicit indexes
        Index("ix_tenants_status", "status"),
        Index("ix_tenants_tier", "tier"),
    )

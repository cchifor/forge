# src/app/data/models/realm.py
"""ORM model for Keycloak realms."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import Base
from app.domain.realm import RealmType
from forge_core.persistence import TimestampMixin


class RealmModel(Base, TimestampMixin):
    __tablename__ = "realms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    realm_type: Mapped[str] = mapped_column(String(20), nullable=False, default=RealmType.DEDICATED)
    keycloak_base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    client_id: Mapped[str] = mapped_column(String(255), nullable=False)
    client_secret: Mapped[str] = mapped_column(Text, nullable=False)
    max_tenants: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_realms_name", "name"),
        Index("ix_realms_realm_type", "realm_type"),
    )

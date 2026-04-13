import uuid

from sqlalchemy import Enum, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.data.models.base import JSON_TYPE, Base
from app.domain.item import ItemStatus
from service.repository.mixins import TenantMixin, TimestampMixin, UserOwnedMixin


class ItemModel(Base, TenantMixin, UserOwnedMixin, TimestampMixin):
    __tablename__ = "items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON_TYPE, default=list)
    status: Mapped[str] = mapped_column(
        Enum(ItemStatus, name="item_status", create_constraint=False, native_enum=False),
        default=ItemStatus.DRAFT,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_items_customer_name", "customer_id", "name"),
        Index("ix_items_customer_status", "customer_id", "status"),
    )

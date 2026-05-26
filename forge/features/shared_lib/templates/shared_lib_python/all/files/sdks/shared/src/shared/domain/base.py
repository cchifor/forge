"""Base domain models shared across backends."""
from __future__ import annotations

from pydantic import BaseModel


class BaseDomainModel(BaseModel):
    """Shared base for all domain value objects."""

    model_config = {"frozen": True}

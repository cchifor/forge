"""Airlock client error types."""

from __future__ import annotations


class AirlockError(Exception):
    """Base error for Airlock client operations."""


class AirlockNotFoundError(AirlockError):
    """Sandbox or resource not found."""


class AirlockTimeoutError(AirlockError):
    """Operation timed out."""

import json

from fastapi import Query
from pydantic import BaseModel, Field


def filter_dict(filter: str = Query(None)):
    if filter is None:
        return {}
    try:
        return json.loads(filter)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in query: {e}") from e


def query_list(query: str = Query(None)):
    if query is None:
        return []
    try:
        return query.split(",")
    except Exception as e:
        raise ValueError(f"Invalid data in query: {e}") from e


class Error(BaseModel):
    """Legacy error payload.

    Prefer :class:`ErrorEnvelope` for new handlers — it implements the
    RFC-007 contract shared with the Node and Rust backends.
    """

    message: str
    type: str
    detail: dict | None = None


class ErrorBody(BaseModel):
    """RFC-007 error body — see docs/rfcs/RFC-007-error-contract.md."""

    code: str
    message: str
    type: str
    context: dict = Field(default_factory=dict)
    correlation_id: str = ""


class ErrorEnvelope(BaseModel):
    """RFC-007 top-level envelope: `{"error": {...}}`."""

    error: ErrorBody

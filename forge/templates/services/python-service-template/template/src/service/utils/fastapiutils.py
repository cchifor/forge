import json

from fastapi import Query
from pydantic import BaseModel


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
    message: str
    type: str
    detail: dict | None = None

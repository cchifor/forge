"""List / inspect / invoke registered agent tools.

Not auth-gated by default. Lock this down before exposing in production —
a leaking /tools endpoint tells attackers exactly which integrations the
service has. Wrap the routes with your auth dependency once you understand
the exposure surface.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from weld.fastapi.security.auth import get_current_user

from app.agents import tool_registry

# Tool listing + invocation must be authenticated (invocation runs registered
# tools). ``get_current_user`` raises 401 when no valid token is present.
router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("")
async def list_tools() -> dict:
    return {
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
                "tags": list(t.tags),
            }
            for t in tool_registry.list()
        ]
    }


@router.post("/{name}/invoke")
async def invoke_tool(name: str, payload: dict[str, Any] | None = None) -> dict:
    try:
        tool = tool_registry.get(name)
    except LookupError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    kwargs = payload or {}
    try:
        result = await tool.invoke(**kwargs)
    except TypeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Bad arguments for tool {name!r}: {e}",
        ) from e
    return {"tool": name, "result": result}

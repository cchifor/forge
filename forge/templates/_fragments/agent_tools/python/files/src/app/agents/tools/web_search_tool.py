"""`web_search` — proxies a search query to Tavily if TAVILY_API_KEY is set.

Deliberately no-op (returns an informative error) when the API key is
absent, so the tool can be registered safely without requiring an external
account to exist at scaffold time.
"""

from __future__ import annotations

import os

from app.agents.tool import Tool, tool_registry


async def _web_search(query: str, max_results: int = 5) -> dict:
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return {
            "error": "TAVILY_API_KEY not set; web_search is disabled",
            "query": query,
            "results": [],
        }
    # Imported lazily so the generated project doesn't need httpx at import
    # time if the user never calls this tool.
    try:
        import httpx  # type: ignore
    except ImportError:
        return {
            "error": "httpx not installed",
            "query": query,
            "results": [],
        }

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "basic",
            },
        )
    if resp.status_code != 200:
        return {"error": f"tavily returned {resp.status_code}", "results": []}
    data = resp.json()
    return {
        "query": query,
        "results": [
            {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("content")}
            for r in data.get("results", [])
        ],
    }


tool = Tool(
    name="web_search",
    description="Search the web via Tavily. Returns title/url/snippet for the top matches.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query"},
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    },
    handler=_web_search,
    tags=("search", "web"),
)

if tool.name not in tool_registry:
    tool_registry.register(tool)

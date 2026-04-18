"""`app tools` — list and invoke registered agent tools.

Only useful when the ``agent_tools`` feature is enabled. Without it the
app.agents package doesn't exist and the commands print a friendly hint.
"""

from __future__ import annotations

import asyncio
import json as _json
from typing import Annotated

import typer

tools_app = typer.Typer(help="Agent tool registry commands")


def _load_registry():
    try:
        from app.agents import tool_registry  # type: ignore
        from app.agents.tool import install_default_tools  # type: ignore
    except ImportError:
        return None, "agent_tools feature not enabled"
    install_default_tools()
    return tool_registry, None


@tools_app.command("list")
def list_tools() -> None:
    """Print the names of all registered tools."""
    registry, err = _load_registry()
    if registry is None:
        typer.echo(err, err=True)
        raise typer.Exit(code=1)
    for tool in registry.list():
        typer.echo(f"{tool.name:<20} {tool.description}")


@tools_app.command("invoke")
def invoke(
    name: Annotated[str, typer.Argument(help="Tool name")],
    args_json: Annotated[
        str, typer.Option("--args", "-a", help="JSON-encoded keyword args")
    ] = "{}",
) -> None:
    """Invoke a tool with JSON-encoded arguments and print the result."""
    registry, err = _load_registry()
    if registry is None:
        typer.echo(err, err=True)
        raise typer.Exit(code=1)
    try:
        tool = registry.get(name)
    except LookupError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(code=1) from e
    try:
        kwargs = _json.loads(args_json)
    except _json.JSONDecodeError as e:
        typer.echo(f"invalid JSON for --args: {e}", err=True)
        raise typer.Exit(code=1) from e

    result = asyncio.run(tool.invoke(**kwargs))
    typer.echo(_json.dumps(result, indent=2, default=str))

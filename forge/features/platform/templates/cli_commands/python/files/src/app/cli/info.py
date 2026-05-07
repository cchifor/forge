"""`app info` — print service metadata + active features."""

from __future__ import annotations

import os
import platform
import sys
from importlib import metadata

import typer

info_app = typer.Typer(help="Service information")


@info_app.command("show")
def show() -> None:
    """Print service runtime info: python, platform, dependencies, features."""
    typer.echo(f"Python:     {sys.version.split()[0]}")
    typer.echo(f"Platform:   {platform.platform()}")
    typer.echo(f"Service:    {metadata.version('app') if _has_pkg('app') else 'unknown'}")
    typer.echo("")
    typer.echo("--- Environment ---")
    for key in ("ENVIRONMENT", "LOG_LEVEL", "DATABASE_URL", "REDIS_URL", "LLM_PROVIDER"):
        val = os.environ.get(key, "<unset>")
        # Scrub passwords from DATABASE_URL display.
        if key == "DATABASE_URL" and "@" in val:
            scheme, _, rest = val.partition("://")
            user, _, host = rest.partition("@")
            val = f"{scheme}://***@{host}"
        typer.echo(f"  {key}: {val}")


def _has_pkg(name: str) -> bool:
    try:
        metadata.version(name)
        return True
    except metadata.PackageNotFoundError:
        return False

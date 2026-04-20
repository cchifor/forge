"""`forge canvas lint <payload.json>` — validate a canvas payload against the manifest."""

from __future__ import annotations

import sys
from pathlib import Path


def _dispatch_canvas(subcommand: str, payload_path: str | None = None) -> None:
    """Dispatch a canvas subcommand and exit."""
    from forge.codegen.canvas_contract import cli_lint  # noqa: PLC0415

    if subcommand == "lint":
        if not payload_path:
            print("error: `forge canvas lint` requires a payload JSON path", file=sys.stderr)
            sys.exit(2)
        code = cli_lint(Path(payload_path))
        sys.exit(code)

    print(f"Unknown canvas subcommand: {subcommand}", file=sys.stderr)
    sys.exit(1)

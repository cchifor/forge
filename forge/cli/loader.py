"""Load config files (YAML / JSON / stdin) into a raw dict."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load_config_file(path_str: str) -> dict[str, Any]:
    """Load YAML or JSON config. Use '-' for stdin."""
    try:
        import yaml  # noqa: PLC0415

        has_yaml = True
    except ImportError:
        has_yaml = False

    try:
        if path_str == "-":
            raw = sys.stdin.read()
        else:
            p = Path(path_str)
            if not p.exists():
                raise FileNotFoundError(f"Config file not found: {p}")
            raw = p.read_text(encoding="utf-8")

        if not raw.strip():
            return {}

        is_yaml = path_str == "-" or Path(path_str).suffix in (".yml", ".yaml")
        if is_yaml and has_yaml:
            return yaml.safe_load(raw) or {}
        return json.loads(raw)
    except Exception as e:
        raise ValueError(f"Failed to load config: {e}") from e

"""Subprocess bridge to the ts-morph Node helper.

Opt-in: ``FORGE_TS_AST=1`` (or ``FORGE_TS_AST=true``) routes ``.ts`` /
``.tsx`` / ``.js`` injections through the ts-morph-backed sidecar
instead of the default regex-based injector. Requires ``node`` on PATH
and ``ts-morph`` npm package reachable via NODE_PATH.

When the sidecar is unavailable or crashes, the caller falls back to
the regex injector — no hard dependency on Node for core forge flows.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


_HELPER_PATH = Path(__file__).with_name("ts-morph-helper.mjs")


def is_enabled() -> bool:
    """``True`` when the user asked for AST injection and it's available."""
    flag = os.getenv("FORGE_TS_AST", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return False
    return shutil.which("node") is not None and _HELPER_PATH.is_file()


def inject_ts_via_morph(
    file: Path,
    feature_key: str,
    marker: str,
    snippet: str,
    position: str,
) -> bool:
    """Invoke the ts-morph helper. Returns ``True`` on success, ``False`` to
    signal the caller should fall back to the regex injector."""
    if not is_enabled():
        return False

    tag = f"{feature_key}:{marker.removeprefix('FORGE:')}"
    request = {
        "op": "inject",
        "file": str(file),
        "tag": tag,
        "marker": marker.removeprefix("FORGE:"),
        "snippet": snippet,
        "position": position,
    }
    try:
        proc = subprocess.run(
            ["node", str(_HELPER_PATH)],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False

    if proc.returncode != 0:
        return False
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return False
    return bool(result.get("ok"))

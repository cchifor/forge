"""Applier for ``.env.example`` appends.

Each ``(key, value)`` pair a fragment declares is appended to
``<backend_dir>/.env.example`` unless an entry for ``key`` is already
present. Idempotent — running a fragment twice doesn't duplicate.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan
    from forge.fragment_context import FragmentContext


def append_env_var(env_file: Path, key: str, value: str) -> None:
    """Append ``KEY=VALUE`` to ``env_file`` unless ``KEY`` is already present.

    Creates parent directories and the file itself if missing. Treats
    each line whose first ``=``-delimited token equals ``key`` as an
    existing entry; subsequent calls with the same ``key`` are no-ops
    even if the value has changed (fragments don't get to overwrite an
    operator's edit).
    """
    line = f"{key}={value}\n"
    if env_file.is_file():
        existing = env_file.read_text(encoding="utf-8")
        for row in existing.splitlines():
            if row.startswith(f"{key}="):
                return
        if not existing.endswith("\n"):
            existing += "\n"
        env_file.write_text(existing + line, encoding="utf-8")
    else:
        env_file.parent.mkdir(parents=True, exist_ok=True)
        env_file.write_text(line, encoding="utf-8")


class FragmentEnvApplier:
    """Idempotent appends to ``<backend_dir>/.env.example``."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.env_vars:
            return
        env_file = ctx.backend_dir / ".env.example"
        for key, value in plan.env_vars:
            append_env_var(env_file, key, value)

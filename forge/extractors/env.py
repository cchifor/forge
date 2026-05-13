"""EnvExtractor — reverse counterpart of :mod:`forge.appliers.env`.

Where :class:`forge.appliers.env.FragmentEnvApplier` appends
``KEY=VALUE`` lines to ``<backend_dir>/.env.example``, this extractor
reads that file and harvests user edits to the values fragments
previously emitted.

Phase 4 implements env-level harvest by parsing the project's
``.env.example`` into a key→value dict and computing the set diff
against the fragment's declared ``env_vars`` tuple. Every divergence
(add / remove / modify) is flagged ``"needs-review"`` — env values
are often default placeholders rather than secrets, but rote
auto-promotion is risky enough that we surface them all for human
review.

Lines that look like comments (``# ...``) and blank lines are
ignored; only ``KEY=value`` rows participate. Quoted values are
preserved verbatim — the extractor doesn't try to undo any shell
escaping, since the forward applier doesn't add any either.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from forge.extractors.pipeline import CandidatePatch

if TYPE_CHECKING:
    from pathlib import Path

    from forge.extractors.plan import ExtractionPlan
    from forge.fragment_context import FragmentContext


class EnvExtractor:
    """Harvest ``.env.example`` value drift."""

    kind = "env"

    def extract(
        self,
        ctx: FragmentContext,
        plan: ExtractionPlan,
    ) -> list[CandidatePatch]:
        """Return harvested candidates for ``plan.env_vars``.

        Reads ``ctx.backend_dir / ".env.example"`` line-by-line (only
        plain ``KEY=value`` rows participate), diffs against
        ``plan.env_vars``, and emits a candidate per add / remove /
        modify. Each candidate carries a structured JSON diff and is
        flagged ``"needs-review"``.

        Skips silently when:

        * ``plan.env_vars`` is empty.
        * ``.env.example`` doesn't exist (some fragments-only-projects
          have no env file; we can't infer drift from nothing).
        """
        if not plan.env_vars:
            return []

        env_file = ctx.backend_dir / ".env.example"
        if not env_file.is_file():
            return []

        project_env = _parse_env_file(env_file)
        fragment_env = {k: v for k, v in plan.env_vars}

        candidates: list[CandidatePatch] = []

        project_keys = set(project_env)
        fragment_keys = set(fragment_env)

        # Removed: fragment-declared, missing from .env.example.
        for key in sorted(fragment_keys - project_keys):
            candidates.append(
                _mk_candidate(
                    plan=plan,
                    ctx=ctx,
                    env_file=env_file,
                    action="removed",
                    key=key,
                    fragment_value=fragment_env[key],
                    project_value=None,
                    rationale=(f"fragment-declared env var '{key}' is missing from .env.example"),
                )
            )

        # Added: in .env.example, not declared by fragment.
        for key in sorted(project_keys - fragment_keys):
            candidates.append(
                _mk_candidate(
                    plan=plan,
                    ctx=ctx,
                    env_file=env_file,
                    action="added",
                    key=key,
                    fragment_value=None,
                    project_value=project_env[key],
                    rationale=(f".env.example carries env var '{key}' that no fragment declares"),
                )
            )

        # Modified: same key, different value.
        for key in sorted(fragment_keys & project_keys):
            f_val = fragment_env[key]
            p_val = project_env[key]
            if f_val == p_val:
                continue
            candidates.append(
                _mk_candidate(
                    plan=plan,
                    ctx=ctx,
                    env_file=env_file,
                    action="modified",
                    key=key,
                    fragment_value=f_val,
                    project_value=p_val,
                    rationale=(
                        f"env var '{key}' value drifted: fragment={f_val!r} project={p_val!r}"
                    ),
                )
            )

        return candidates


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=value`` rows from ``path``, ignoring comments + blanks.

    Returns a dict mapping key to value-as-stored (no quote stripping,
    no shell expansion — the forward applier writes literal values
    too). Lines without ``=`` are skipped silently; the user may have
    added free-form comments or section dividers.
    """
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        out[key] = value.strip()
    return out


def _mk_candidate(
    *,
    plan: ExtractionPlan,
    ctx: FragmentContext,
    env_file: Path,
    action: str,
    key: str,
    fragment_value: str | None,
    project_value: str | None,
    rationale: str,
) -> CandidatePatch:
    """Build an ``env`` candidate patch with a structured-JSON diff."""
    payload = {
        "action": action,
        "key": key,
        "fragment_value": fragment_value,
        "project_value": project_value,
    }
    diff = json.dumps(payload, sort_keys=True, indent=2)
    try:
        rel_path = env_file.relative_to(ctx.project_root).as_posix()
    except ValueError:
        rel_path = env_file.name
    return CandidatePatch(
        fragment=plan.fragment_name,
        backend=ctx.backend_config.name,
        kind="env",
        rel_path=rel_path,
        target_path=str(env_file),
        diff=diff,
        baseline_sha=None,
        current_sha="",
        risk="needs-review",
        rationale=rationale,
    )

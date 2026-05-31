"""WS-8.5: every GitHub Action ref must be pinned to a commit SHA.

Floating tags (``@stable``, ``@v4``) are a supply-chain risk — a compromised
upstream tag silently runs in CI with repo permissions. Pin to 40-hex SHAs.
Also assert dependabot covers the polyglot ecosystems forge generates.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
_DEPENDABOT = Path(__file__).resolve().parent.parent / ".github" / "dependabot.yml"

# uses: owner/repo@<ref>  — capture the ref. Local (./...) and docker refs skip.
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s+([^\s@]+)@(\S+)")
_SHA = re.compile(r"^[0-9a-f]{40}$")


def _floating_refs() -> list[str]:
    floating: list[str] = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        for i, line in enumerate(wf.read_text(encoding="utf-8").splitlines(), 1):
            m = _USES.match(line)
            if not m:
                continue
            owner_repo, ref = m.group(1), m.group(2)
            if owner_repo.startswith("."):
                continue
            if not _SHA.match(ref):
                floating.append(f"{wf.name}:{i}: {owner_repo}@{ref}")
    return floating


def test_all_actions_pinned_to_sha():
    floating = _floating_refs()
    assert not floating, "floating (non-SHA) action refs found:\n" + "\n".join(floating)


def test_dependabot_covers_polyglot_ecosystems():
    doc = yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))
    ecos = {u["package-ecosystem"] for u in doc["updates"]}
    for required in ("pip", "github-actions", "npm", "cargo", "pub"):
        assert required in ecos, f"dependabot missing ecosystem: {required}"

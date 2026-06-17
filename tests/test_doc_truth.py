"""#258 — doc-truth CI gate.

Mechanical validation of doc claims that silently rot: version strings,
registry-count badges, relative links, and documented ``forge`` CLI flags.
This is the drift class that produced the ``--template`` and stale-model-id
bugs — a doc said something the code no longer backed.

Each check is deliberately conservative (zero false positives against the
current tree) so a red here always means a real doc/code divergence.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Repo-root markdown + everything under docs/. Used by the link checker.
_ALL_DOCS: list[Path] = [
    *(
        _REPO_ROOT / name
        for name in (
            "README.md",
            "CHANGELOG.md",
            "UPGRADING.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "RELEASING.md",
        )
    ),
    *sorted((_REPO_ROOT / "docs").glob("**/*.md")),
]

# Docs a user actually follows to drive the CLI. RFCs / ADRs are excluded
# on purpose — they describe proposed or historical interfaces, not the
# shipped flag surface.
_USER_FACING_DOCS: list[Path] = [
    _REPO_ROOT / "README.md",
    _REPO_ROOT / "UPGRADING.md",
    _REPO_ROOT / "docs" / "OPERATIONAL_RUNBOOK.md",
    _REPO_ROOT / "docs" / "GETTING_STARTED.md",
]


def _readme() -> str:
    return (_REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _badge(metric: str) -> str:
    """Return the value segment of a shields.io ``badge/<metric>-<value>-`` URL."""
    m = re.search(rf"badge/{re.escape(metric)}-([^-?]+)-", _readme())
    assert m, f"README badge for {metric!r} not found"
    return m.group(1)


class TestVersionTruth:
    def test_readme_version_badge_matches_package(self) -> None:
        from forge import __version__

        assert _badge("version") == __version__, (
            f"README version badge {_badge('version')!r} != forge.__version__ "
            f"{__version__!r} — bump the badge."
        )

    def test_readme_python_badge_matches_pyproject(self) -> None:
        data = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        requires_python = data["project"]["requires-python"]
        # Badge value is URL-encoded, e.g. ``%3E%3D3.13`` -> ``>=3.13``.
        assert unquote(_badge("python")) == requires_python, (
            f"README python badge {unquote(_badge('python'))!r} != "
            f"pyproject requires-python {requires_python!r}."
        )


class TestRegistryCountTruth:
    def test_backends_badge_matches_registry(self) -> None:
        from forge.config import BACKEND_REGISTRY

        assert int(_badge("backends")) == len(BACKEND_REGISTRY), (
            f"README backends badge {_badge('backends')} != "
            f"len(BACKEND_REGISTRY) {len(BACKEND_REGISTRY)}."
        )

    def test_frontends_badge_matches_registry(self) -> None:
        from forge.config import available_frontend_frameworks

        # The badge counts real frameworks; ``none`` is the absence of one.
        real = [f for f in available_frontend_frameworks() if f != "none"]
        assert int(_badge("frontends")) == len(real), (
            f"README frontends badge {_badge('frontends')} != "
            f"{len(real)} real frameworks {real}."
        )

    def test_options_badge_matches_registry(self) -> None:
        from forge.options import OPTION_REGISTRY

        assert int(_badge("options")) == len(OPTION_REGISTRY), (
            f"README options badge {_badge('options')} != "
            f"len(OPTION_REGISTRY) {len(OPTION_REGISTRY)}."
        )


class TestRelativeLinksResolve:
    _LINK = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")

    def test_all_doc_relative_links_resolve(self) -> None:
        broken: list[str] = []
        for doc in _ALL_DOCS:
            if not doc.exists():
                continue
            for m in self._LINK.finditer(doc.read_text(encoding="utf-8")):
                link = m.group(1).strip()
                if link.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                rel = link.split("#", 1)[0]
                if not rel:
                    continue
                target = (doc.parent / rel).resolve()
                if not target.exists():
                    broken.append(f"{doc.relative_to(_REPO_ROOT)} -> {link}")
        assert not broken, "Unresolved relative doc links:\n" + "\n".join(broken)


class TestDocumentedCliFlagsExist:
    _FENCE = re.compile(r"```(.*?)```", re.DOTALL)
    _CMD_LINE = re.compile(r"^\s*(?:\$\s*)?forge\s+(.*)$")
    _FLAG = re.compile(r"--[a-z][a-z0-9-]+")

    def _parser_flags(self) -> set[str]:
        from forge.cli.parser import _build_parser

        return {
            s
            for a in _build_parser()._actions
            for s in a.option_strings
            if s.startswith("--")
        }

    def test_user_facing_forge_invocations_use_real_flags(self) -> None:
        parser_flags = self._parser_flags()
        missing: list[str] = []
        for doc in _USER_FACING_DOCS:
            if not doc.exists():
                continue
            for block in self._FENCE.findall(doc.read_text(encoding="utf-8")):
                for line in block.splitlines():
                    m = self._CMD_LINE.match(line)
                    if not m:
                        continue
                    # Only the first command in a pipeline/chain is ``forge``.
                    run = re.split(r"[|&;]", m.group(1))[0]
                    for flag in self._FLAG.findall(run):
                        if flag not in parser_flags:
                            missing.append(
                                f"{doc.relative_to(_REPO_ROOT)}: {flag} "
                                f"(in `forge {m.group(1).strip()}`)"
                            )
        assert not missing, (
            "Docs reference forge CLI flags that do not exist in the parser:\n"
            + "\n".join(missing)
        )

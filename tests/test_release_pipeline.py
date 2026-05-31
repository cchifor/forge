"""WS-4.1/4.2: release-pipeline helper scripts.

The release workflow used ``contains(github.ref_name, '-')`` to detect a
prerelease — which misclassifies PEP440 tags like ``v1.2.0a1`` (no hyphen)
as STABLE, publishing an alpha to prod PyPI / npm latest / a stable GitHub
release. And it greps the CHANGELOG for ``## [<version>]`` which doesn't
exist (only ``[Unreleased]`` does) → empty release notes. Both are now
shell helpers under .github/scripts/, exercised here so a regression is
caught without pushing a tag.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# These helpers are POSIX release-pipeline scripts that only ever run on the
# ubuntu release runners (`.github/workflows/release.yml`). Exercising them
# through git-bash on windows-latest tests a scenario that never happens in
# production and trips a git-bash quirk where the script exits non-zero after a
# successful `GITHUB_OUTPUT` append (even with the write guarded). The logic is
# fully covered on the ubuntu + macos legs.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="release helper bash scripts run only on ubuntu CI (release.yml); "
    "not a supported target on Windows.",
)

_REPO = Path(__file__).resolve().parent.parent
_DETECT = _REPO / ".github" / "scripts" / "detect-prerelease.sh"
_EXTRACT = _REPO / ".github" / "scripts" / "extract-changelog.sh"


def _detect(tag: str) -> str:
    out = subprocess.run(
        ["bash", str(_DETECT), tag],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_scripts_exist_and_executable():
    assert _DETECT.is_file(), _DETECT
    assert _EXTRACT.is_file(), _EXTRACT
    assert os.access(_DETECT, os.X_OK), "detect-prerelease.sh must be executable"
    assert os.access(_EXTRACT, os.X_OK), "extract-changelog.sh must be executable"


@pytest.mark.parametrize("tag", ["v1.2.0", "1.2.0", "v2.0.0", "v1.2.0.post1"])
def test_stable_versions(tag):
    assert _detect(tag) == "is_prerelease=false", tag


@pytest.mark.parametrize(
    "tag",
    [
        "v1.2.0a1",  # PEP440 alpha — the headline bug
        "v1.2.0b1",  # PEP440 beta
        "v1.2.0rc1",  # PEP440 rc
        "1.2.0a1",  # no leading v
        "v1.2.0.dev1",  # PEP440 dev
        "v1.2.0-alpha",  # legacy hyphen
        "v1.2.0-alpha.1",  # legacy hyphen
        "v1.2.0-rc.1",  # legacy hyphen
    ],
)
def test_prereleases(tag):
    assert _detect(tag) == "is_prerelease=true", tag


def test_detect_writes_github_output(tmp_path):
    out_file = tmp_path / "gh_out"
    env = {**os.environ, "GITHUB_OUTPUT": str(out_file)}
    subprocess.run(["bash", str(_DETECT), "v1.2.0a1"], check=True, env=env)
    assert "is_prerelease=true" in out_file.read_text()


def test_detect_rejects_missing_arg():
    rc = subprocess.run(["bash", str(_DETECT)], capture_output=True, text=True)
    assert rc.returncode == 2


def test_detect_rejects_garbage():
    rc = subprocess.run(["bash", str(_DETECT), "not-a-version"], capture_output=True, text=True)
    assert rc.returncode == 3


def _write_changelog(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "CHANGELOG.md"
    p.write_text(body, encoding="utf-8")
    return p


def test_extract_unreleased_non_empty(tmp_path):
    cl = _write_changelog(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n\n### Added\n- a new thing\n\n## [1.0.0] - 2026-01-01\n\n- old\n",
    )
    out = subprocess.run(
        ["bash", str(_EXTRACT), "Unreleased", str(cl)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "a new thing" in out.stdout
    assert "old" not in out.stdout, "must stop at the next ## [ heading"


def test_extract_dated_version(tmp_path):
    cl = _write_changelog(
        tmp_path,
        "# Changelog\n\n## [Unreleased]\n\n- wip\n\n## [1.0.0] - 2026-01-01\n\n- shipped feature\n",
    )
    out = subprocess.run(
        ["bash", str(_EXTRACT), "1.0.0", str(cl)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "shipped feature" in out.stdout
    assert "wip" not in out.stdout


def test_extract_missing_version_fails(tmp_path):
    cl = _write_changelog(tmp_path, "# Changelog\n\n## [1.0.0]\n\n- x\n")
    rc = subprocess.run(["bash", str(_EXTRACT), "2.0.0", str(cl)], capture_output=True, text=True)
    assert rc.returncode == 1, "missing section must fail, not emit empty notes"


def test_extract_empty_section_fails(tmp_path):
    cl = _write_changelog(tmp_path, "# Changelog\n\n## [Unreleased]\n\n## [1.0.0]\n\n- x\n")
    rc = subprocess.run(
        ["bash", str(_EXTRACT), "Unreleased", str(cl)], capture_output=True, text=True
    )
    assert rc.returncode == 1, "empty section must fail loudly"

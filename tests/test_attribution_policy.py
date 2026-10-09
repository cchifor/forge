"""Historical attribution cleanup preserves human credit and source trees."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.check_attribution import violations
from scripts.prepare_attribution_cleanup import clean_message


def test_cleanup_removes_only_claude_coauthor_lines():
    message = (
        b"Document Claude integration\n\n"
        b"Co-authored-by: Human Developer <human@example.com>\n"
        b"Co-Authored-By: Claude <noreply@anthropic.com>\n"
        b"Reviewed-by: Human Reviewer <review@example.com>\n"
    )
    assert clean_message(message) == (
        b"Document Claude integration\n\n"
        b"Co-authored-by: Human Developer <human@example.com>\n"
        b"Reviewed-by: Human Reviewer <review@example.com>\n"
    )
    assert clean_message(b"Use Claude skills\n") == b"Use Claude skills\n"


def test_new_commit_policy_respects_revision_range(tmp_path: Path):
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init")
    git("config", "user.name", "Human Developer")
    git("config", "user.email", "human@example.com")
    git("commit", "--allow-empty", "-m", "Existing history")
    base = git("rev-parse", "HEAD")
    git("commit", "--allow-empty", "-m", "Human work\n\nCo-authored-by: Jane <jane@example.com>")
    assert violations(str(tmp_path), f"{base}..HEAD") == []
    git(
        "commit",
        "--allow-empty",
        "-m",
        "New work\n\nCo-authored-by: Claude <noreply@anthropic.com>",
    )
    bad = git("rev-parse", "HEAD")
    assert violations(str(tmp_path), f"{base}..HEAD") == [bad]
    git("commit", "--allow-empty", "-m", "Use Claude as a supported agent")
    assert violations(str(tmp_path), "HEAD^..HEAD") == []

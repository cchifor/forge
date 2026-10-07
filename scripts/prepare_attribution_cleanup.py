"""Prepare and verify an attribution-only rewrite without publishing history."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def git(directory: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=directory, check=True, capture_output=True, text=True
    ).stdout.strip()


def clean_message(message: bytes) -> bytes:
    return b"".join(
        line
        for line in message.splitlines(keepends=True)
        if not re.match(rb"(?i)^co-authored-by:.*(?:\bClaude\b|noreply@anthropic\.com)", line)
    )


def prepare(source: Path, destination: Path) -> dict:
    source, destination = source.resolve(), destination.resolve()
    if destination.exists() or destination.is_relative_to(source):
        raise ValueError("Choose a new destination outside the working repository")
    destination.mkdir(parents=True)
    mirror = destination / "rewritten.git"
    partial = subprocess.run(
        ["git", "config", "--get", "remote.origin.promisor"],
        cwd=source,
        capture_output=True,
        text=True,
    ).stdout.strip()
    clone_source = git(source, "remote", "get-url", "origin") if partial == "true" else str(source)
    subprocess.run(
        ["git", "clone", "--mirror", "--no-local", clone_source, str(mirror)], check=True
    )
    git(mirror, "bundle", "create", str(destination / "before.bundle"), "--all")
    before = git(mirror, "rev-parse", "refs/heads/main")
    originals = {
        commit: (
            git(mirror, "show", "-s", "--format=%T%n%an%n%ae%n%aI%n%cn%n%ce%n%cI", commit),
            git(mirror, "show", "-s", "--format=%B", commit).encode(),
        )
        for commit in git(mirror, "rev-list", "--all").splitlines()
    }
    main_tree = git(mirror, "rev-parse", before + "^{tree}")
    callback = r"""import re
commit.message = b"".join(line for line in commit.message.splitlines(keepends=True) if not re.match(br"(?i)^co-authored-by:.*(?:\bClaude\b|noreply@anthropic\.com)", line))
"""
    subprocess.run(
        [
            "uvx",
            "--from",
            "git-filter-repo==2.47.0",
            "git-filter-repo",
            "--preserve-commit-hashes",
            "--commit-callback",
            callback,
        ],
        cwd=mirror,
        check=True,
    )
    mapping = (mirror / "filter-repo/commit-map").read_text()
    (destination / "commit-map.txt").write_text(mapping)
    changed = verified = 0
    for row in mapping.splitlines()[1:]:
        old, new = row.split()
        if set(new) == {"0"}:
            raise ValueError(f"Rewrite unexpectedly removed commit {old}")
        before_data, old_message = originals[old]
        after_data = git(mirror, "show", "-s", "--format=%T%n%an%n%ae%n%aI%n%cn%n%ce%n%cI", new)
        if before_data != after_data:
            raise ValueError(f"Tree or human identity changed for {old}")
        new_message = git(mirror, "show", "-s", "--format=%B", new).encode()
        if clean_message(old_message).strip() != new_message.strip():
            raise ValueError(f"Unexpected message change for {old}")
        verified += 1
        changed += old != new
    after = git(mirror, "rev-parse", "refs/heads/main")
    result = {
        "published": False,
        "old_main": before,
        "new_main": after,
        "verified_commits": verified,
        "changed_commit_ids": changed,
        "main_tree_unchanged": main_tree == git(mirror, "rev-parse", after + "^{tree}"),
        "backup": str(destination / "before.bundle"),
        "mirror": str(mirror),
        "note": "Rewriting history invalidates commit signatures and old commit links. No remote refs were changed.",
    }
    (destination / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("."))
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.destination), indent=2))

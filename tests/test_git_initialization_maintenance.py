"""Initial generation must finish automatic Git maintenance before returning."""

import hashlib
import json
import shutil
import subprocess

import pytest

from forge.generator import _git_init


@pytest.mark.skipif(shutil.which("git") is None, reason="git required")
def test_initial_commit_completes_forced_maintenance_in_foreground(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True, check=True
        ).stdout.strip()

    git("init", "--object-format=sha1")
    for key, value in {
        "gc.auto": "1",
        "gc.autoDetach": "true",
        "maintenance.autoDetach": "true",
        "maintenance.auto": "true",
        "maintenance.strategy": "gc",
    }.items():
        git("config", key, value)
    # Git's loose-object heuristic samples the 17/ bucket. Supply enough real
    # blobs there to trigger collection deterministically with gc.auto=1.
    found = 0
    for number in range(10000):
        content = f"generation source {number}\n".encode()
        blob = b"blob " + str(len(content)).encode() + b"\0" + content
        if hashlib.sha1(blob).hexdigest().startswith("17"):
            (root / f"source-{found}.txt").write_bytes(content)
            found += 1
            if found == 3:
                break
    assert found == 3

    trace = tmp_path / "git-trace.jsonl"
    monkeypatch.setenv("GIT_TRACE2_EVENT", str(trace))
    monkeypatch.setenv("GIT_TRACE2_CONFIG_PARAMS", "gc.autoDetach,maintenance.autoDetach")
    _git_init(root)
    events = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()]
    commit = next(
        e["sid"] for e in events if e.get("event") == "cmd_name" and e.get("name") == "commit"
    )
    gc = next(e["sid"] for e in events if e.get("event") == "cmd_name" and e.get("name") == "gc")
    exits = {e["sid"]: i for i, e in enumerate(events) if e.get("event") == "exit"}
    assert exits[gc] < exits[commit]
    effective = {
        e["param"].lower(): e["value"]
        for e in events
        if e.get("event") == "def_param" and e["sid"] == commit
    }
    assert effective["gc.autodetach"] == "false"
    assert effective["maintenance.autodetach"] == "false"
    assert list((root / ".git/objects/pack").glob("*.pack"))
    assert "count: 0" in git("count-objects", "-v")
    # Overrides apply only to initialization, never to the user's preferences.
    assert git("config", "gc.autoDetach") == "true"
    assert git("config", "maintenance.autoDetach") == "true"

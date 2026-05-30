"""Tests for alembic migration rechaining (forge.codegen.migration_chain).

Fragments hard-code revision/down_revision assuming a fixed set; any subset
collides (two 0003s) or gaps (0005 -> missing 0004). rechain_migrations renumbers
the present files into one valid linear history.
"""

from __future__ import annotations

import re
from pathlib import Path

from forge.codegen.migration_chain import rechain_migrations

_REV = re.compile(r'^revision\s*(?::[^=]+)?=\s*(?:"([^"]*)"|None)', re.M)
_DOWN = re.compile(r'^down_revision\s*(?::[^=]+)?=\s*(?:"([^"]*)"|None)', re.M)


def _write(path: Path, *, rev: str, down: str) -> None:
    down_val = "None" if down == "None" else f'"{down}"'
    path.write_text(
        f'"""mig."""\nfrom typing import Union\n'
        f'revision: str = "{rev}"\n'
        f"down_revision: Union[str, None] = {down_val}\n"
        f"def upgrade() -> None: ...\n"
        f"def downgrade() -> None: ...\n",
        encoding="utf-8",
    )


def _rev(p: Path) -> str:
    m = _REV.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m and m.group(1) is not None else "None"


def _down(p: Path) -> str:
    m = _DOWN.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m and m.group(1) is not None else "None"


def test_rechain_fixes_collisions_and_gaps(tmp_path: Path) -> None:
    _write(tmp_path / "0001_initial.py", rev="0001", down="None")
    _write(tmp_path / "0002_conv.py", rev="0002", down="0001")
    _write(tmp_path / "0003_chat.py", rev="0003", down="0002")
    _write(tmp_path / "0003_rag.py", rev="0003", down="0002")  # collision
    _write(tmp_path / "0005_webhooks.py", rev="0005", down="0004")  # gap

    rechain_migrations(tmp_path)

    files = sorted(p for p in tmp_path.glob("*.py") if not p.name.startswith("__"))
    revs = {p.name: _rev(p) for p in files}
    downs = {p.name: _down(p) for p in files}

    # 1. Revisions are unique.
    assert len(set(revs.values())) == len(revs), revs
    # 2. Exactly one root (down_revision None).
    roots = [name for name, d in downs.items() if d == "None"]
    assert roots == ["0001_initial.py"], roots
    # 3. Every non-root down_revision points to a present revision.
    present = set(revs.values())
    for d in downs.values():
        if d != "None":
            assert d in present, d
    # 4. Exactly one head (linear history, no branches).
    targets = {d for d in downs.values() if d != "None"}
    heads = present - targets
    assert len(heads) == 1, heads


def test_rechain_preserves_order_and_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path / "0001_initial.py", rev="0001", down="None")
    _write(tmp_path / "0002_conv.py", rev="0002", down="0001")
    _write(tmp_path / "0005_webhooks.py", rev="0005", down="0004")
    rechain_migrations(tmp_path)
    # webhooks sorts after conv (5 > 2), so chains off it; base stays root.
    assert _down(tmp_path / "0002_conv.py") == _rev(tmp_path / "0001_initial.py")
    assert _down(tmp_path / "0005_webhooks.py") == _rev(tmp_path / "0002_conv.py")


def test_rechain_noop_on_missing_dir(tmp_path: Path) -> None:
    rechain_migrations(tmp_path / "nope")  # must not raise

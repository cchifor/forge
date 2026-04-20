"""`forge preview --diff` — dry-run generation and diff against the output dir.

Generates into a tempdir (via ``generator.generate(dry_run=True)``) and
then diffs the tempdir against the configured ``--output-dir``. Useful
as a sanity check before committing to an overwrite — shows what will
change without touching the filesystem.
"""

from __future__ import annotations

import difflib
import sys
from pathlib import Path


def _dispatch_preview(args) -> None:
    from forge.cli.builder import _build_config  # noqa: PLC0415
    from forge.cli.loader import _load_config_file  # noqa: PLC0415
    from forge.generator import generate  # noqa: PLC0415

    try:
        cfg = _load_config_file(args.config) if args.config else {}
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    try:
        config = _build_config(args, cfg)
        config.validate()
    except (ValueError, KeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(2)

    output_dir = Path(config.output_dir).resolve() / config.project_slug
    print(f"forge preview: diff against {output_dir}")
    print()

    preview_root = generate(config, quiet=True, dry_run=True)

    changes = _diff_trees(preview_root, output_dir)
    if not changes:
        print("No changes — preview matches the current output exactly.")
        sys.exit(0)

    for kind, path, unified_diff in changes:
        prefix = {"added": "+", "removed": "-", "modified": "~"}[kind]
        print(f"{prefix} {path}")
        if unified_diff:
            for line in unified_diff[:30]:
                print(f"    {line.rstrip()}")
            if len(unified_diff) > 30:
                print(f"    ... ({len(unified_diff) - 30} more lines)")
    print()
    print(f"{len(changes)} change(s) — re-run `forge` without --preview to apply.")
    sys.exit(0)


def _diff_trees(preview_root: Path, existing_root: Path) -> list[tuple[str, str, list[str] | None]]:
    """Return list of (kind, rel_path, unified_diff_lines|None).

    kind is one of "added", "removed", "modified".
    """
    preview_files = _walk(preview_root)
    existing_files = _walk(existing_root) if existing_root.is_dir() else {}

    out: list[tuple[str, str, list[str] | None]] = []
    all_keys = sorted(set(preview_files) | set(existing_files))
    for key in all_keys:
        if key in preview_files and key not in existing_files:
            out.append(("added", key, None))
        elif key in existing_files and key not in preview_files:
            out.append(("removed", key, None))
        else:
            new_bytes = preview_files[key]
            old_bytes = existing_files[key]
            if new_bytes == old_bytes:
                continue
            # Produce unified diff for text files only; bytes-equal binary
            # files short-circuit above, bytes-different binary files get
            # a note rather than a diff body.
            try:
                new_text = new_bytes.decode("utf-8").splitlines()
                old_text = old_bytes.decode("utf-8").splitlines()
                diff = list(
                    difflib.unified_diff(
                        old_text,
                        new_text,
                        fromfile=f"a/{key}",
                        tofile=f"b/{key}",
                        lineterm="",
                    )
                )
                out.append(("modified", key, diff))
            except UnicodeDecodeError:
                out.append(("modified", key, ["<binary file>"]))
    return out


def _walk(root: Path) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    if not root.is_dir():
        return out
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        out[rel] = p.read_bytes().replace(b"\r\n", b"\n")
    return out

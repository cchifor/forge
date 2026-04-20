"""`forge migrate [--only NAME | --skip NAME] [--dry-run]` — umbrella codemod runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _dispatch_migrate(args) -> None:
    from forge.migrations import apply_migrations  # noqa: PLC0415

    project_path = Path(getattr(args, "project_path", ".")).resolve()
    if not (project_path / "forge.toml").is_file():
        print(
            f"error: no forge.toml at {project_path}. Run inside a forge-generated project.",
            file=sys.stderr,
        )
        sys.exit(2)

    only = getattr(args, "migrate_only", None)
    skip = getattr(args, "migrate_skip", None)
    dry = bool(getattr(args, "dry_run", False))
    quiet = bool(getattr(args, "quiet", False))
    json_out = bool(getattr(args, "json_output", False))

    only_list = [o.strip() for o in only.split(",") if o.strip()] if only else None
    skip_list = [s.strip() for s in skip.split(",") if s.strip()] if skip else None

    reports = apply_migrations(
        project_path,
        only=only_list,
        skip=skip_list,
        dry_run=dry,
        quiet=quiet,
    )

    if json_out:
        sys.stdout.write(json.dumps([r.as_dict() for r in reports], indent=2) + "\n")
    elif not quiet:
        print()
        for r in reports:
            applied = "APPLIED" if r.applied else "SKIPPED"
            print(f"  {applied:<8} migrate-{r.name}")
            for change in r.changes:
                print(f"    - {change}")
            if r.skipped_reason:
                print(f"    (reason: {r.skipped_reason})")
    sys.exit(0)

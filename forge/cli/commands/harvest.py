"""``forge --harvest`` — reverse-direction extraction CLI dispatcher.

Phase 4 of the bidirectional-sync plan. Counterpart of ``forge --update``
(forward apply) and ``forge --verify`` (read-only drift). The dispatcher
resolves the project root, hands off to :func:`harvest_project`,
optionally writes the bundle to disk, and maps the result to an exit
code:

* ``0`` — bundle written cleanly (or empty bundle — no harvest needed).
* ``11`` — at least one ``conflict`` candidate present. The bundle is
  still written; the exit code surfaces the conflict to CI gates.

A future Phase 4b PR will add ``--accept-harvested`` (auto-apply) and
``--emit-pr`` (open a PR against the fragment repo); this dispatcher
keeps the surface stable so those callers slot in without changing
``main.py``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from forge.errors import EXIT_VERIFY_CONFLICT, PROVENANCE_MANIFEST_MISSING, ProvenanceError
from forge.sync.project_to_forge.harvester import harvest_project

# Exit code when the harvest target has no forge.toml. Mirrors the
# ``--verify`` dispatcher so the harvest verb's exit codes stay
# consistent with the broader CLI taxonomy (5 = manifest IO failure).
_EXIT_MANIFEST_MISSING = 5


def _run_harvest(args: argparse.Namespace) -> int:
    """Dispatch ``forge --harvest``. Returns the exit code.

    Resolves ``--project-path`` (defaulting to the current directory),
    invokes :func:`harvest_project`, prints the bundle in JSON shape
    when ``--harvest-out=-``, and returns 0 / 11 based on whether any
    ``conflict`` candidates were emitted. Never raises — every failure
    path surfaces as a non-zero return.
    """
    project_root = Path(getattr(args, "project_path", ".") or ".").resolve()
    out_dir_arg = getattr(args, "harvest_out", ".forge-harvest")
    out_dir: Path | None = None if out_dir_arg == "-" else Path(out_dir_arg).resolve()

    scope_arg = getattr(args, "harvest_scope", None)
    scope: tuple[str, ...] | None = (
        tuple(s.strip() for s in scope_arg.split(",") if s.strip()) if scope_arg else None
    )

    include_arg = getattr(args, "harvest_include", "all")
    include: tuple[str, ...] = (
        ("files", "blocks", "deps", "env") if include_arg == "all" else (include_arg,)
    )

    interactive = bool(getattr(args, "harvest_interactive", False))
    quiet = bool(getattr(args, "quiet", False)) or bool(getattr(args, "json_output", False))

    try:
        bundle = harvest_project(
            project_root,
            out_dir=out_dir,
            scope=scope,
            include=include,
            interactive=interactive,
            quiet=quiet,
        )
    except ProvenanceError as e:
        # The harvester raises ProvenanceError(PROVENANCE_MANIFEST_MISSING)
        # when no forge.toml is present at project_root. Surface a
        # structured error so JSON consumers can branch on a known shape,
        # then exit with the manifest-missing code (5).
        if e.code == PROVENANCE_MANIFEST_MISSING:
            if out_dir is None:
                sys.stdout.write(json.dumps({"error": f"no forge.toml at {project_root}"}) + "\n")
            else:
                sys.stderr.write(f"forge --harvest: no forge.toml at {project_root}\n")
            return _EXIT_MANIFEST_MISSING
        raise

    # Streaming JSON mode: write the bundle envelope to stdout instead
    # of materialising a directory. Symmetric to ``forge --verify --json``.
    if out_dir is None:
        sys.stdout.write(json.dumps(bundle.to_dict(), indent=2) + "\n")

    if not bundle.candidates:
        return 0

    # Conflicts produce a non-zero exit so CI gates that wrap harvest
    # see the failure even when the bundle directory is materialised.
    if any(c.risk == "conflict" for c in bundle.candidates):
        return EXIT_VERIFY_CONFLICT

    return 0

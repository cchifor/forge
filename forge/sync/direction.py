"""Shared direction/scope union types for sync operations.

Phase 3 of the bidirectional-sync plan consolidates the typed Literals
that both the forward (``forge --update``) and reverse
(``forge --verify``, Phase 4 ``forge --harvest``) flows share. Keeping
them here means the forward and reverse call sites import the same
canonical types instead of redefining them per-direction.

``UpdateMode`` was previously defined in
:mod:`forge.fragment_context`; that location keeps a re-export so
external callers (plugins, tests) that imported from the old path keep
working.

``VerifyScope`` and ``VerifyFailOn`` mirror the same enumeration the
read-only verify command uses internally (see
:mod:`forge.sync.project_to_forge.verify`); the canonical home is here
so the harvest flow can share them without a project_to_forge → core
back-edge.
"""

from __future__ import annotations

from typing import Literal

# File-copy collision behaviour for the apply pass.
#
#   * ``"strict"``    — fresh generation; fragments may not overlap the
#                       base template or each other.
#   * ``"merge"``     — three-way decide vs the manifest's baseline; emit
#                       ``.forge-merge`` sidecars on conflict.
#   * ``"skip"``      — preserve any pre-existing destination
#                       unconditionally (pre-1.1 update behaviour).
#   * ``"overwrite"`` — clobber pre-existing destinations.
#
# The CLI ``--mode`` flag for ``forge --update`` only exposes the last
# three; ``"strict"`` is the fresh-generation default.
UpdateMode = Literal["strict", "merge", "skip", "overwrite"]

# Which record kinds ``verify_project`` should walk.
#
#   * ``"all"``       — provenance entries + merge blocks (default).
#   * ``"files"``     — file-level provenance only; skip merge blocks.
#   * ``"blocks"``    — merge blocks only; skip file provenance.
#   * ``"fragments"`` — both kinds, but in principle could later filter
#                       to ``origin == "fragment"`` records. Treated as
#                       ``"all"`` today.
VerifyScope = Literal["all", "files", "blocks", "fragments"]

# Threshold for non-zero exit at the CLI layer.
#
#   * ``"drift"``    — exit non-zero on any drift OR conflict (default).
#   * ``"conflict"`` — exit non-zero only on conflict; drift alone passes.
#   * ``"never"``    — always exit zero (use the JSON output for
#                      downstream branching).
VerifyFailOn = Literal["drift", "conflict", "never"]

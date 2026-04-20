"""Read and write the project-root ``forge.toml`` manifest.

``forge.toml`` is the source of truth for ``forge --update``: it records
which forge version generated the project, where the templates live, and
every Option value the user set.

Canonical format:

    [forge]
    version = "0.2.0"
    project_name = "acme"

    [forge.templates]
    python = "services/python-service-template"

    [forge.options]
    "middleware.rate_limit" = true
    "middleware.security_headers" = true
    "rag.backend" = "qdrant"
    "rag.embeddings" = "voyage"
    "rag.top_k" = 10

Pre-Option shapes (legacy ``[forge.features.*]`` /
``[forge.parameters]`` tables) are rejected with a clear error pointing
to ``forge.toml`` re-generation — the refactor is a hard cutover.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit

logger = logging.getLogger(__name__)


@dataclass
class ForgeTomlData:
    """Parsed ``forge.toml`` contents."""

    version: str
    project_name: str
    templates: dict[str, str] = field(default_factory=dict)
    # Dotted option path → value. Only paths the user explicitly set
    # appear here (the resolver fills in defaults).
    options: dict[str, Any] = field(default_factory=dict)
    # Per-path provenance for files the generator emitted. See
    # ``forge.provenance`` for the recording / classification primitives.
    # Keys are POSIX-style relative paths; values are
    # ``{origin, sha256, fragment_name?, fragment_version?}`` dicts.
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    # Per-block SHA baselines for merge-zone injections (1.0.0a3+).
    # Keys are ``{rel_path}::{feature_key}:{marker}``.
    merge_blocks: dict[str, dict[str, str]] = field(default_factory=dict)


def read_forge_toml(path: Path) -> ForgeTomlData:
    """Parse ``forge.toml`` into a structured object.

    Raises ``FileNotFoundError`` if the file is missing and ``ValueError``
    on malformed content or legacy-shape tables.
    """
    if not path.is_file():
        raise FileNotFoundError(f"forge.toml not found at {path}")
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))

    forge = doc.get("forge")
    if forge is None:
        raise ValueError(f"{path}: missing [forge] section")

    # Reject legacy tables up front — do not silently auto-migrate.
    if "features" in forge:
        raise ValueError(
            f"{path}: found legacy [forge.features] table. This forge.toml "
            "was written by a pre-Option forge; the current forge uses "
            "[forge.options] exclusively. Regenerate the project with the "
            "current forge to migrate."
        )
    if "parameters" in forge:
        raise ValueError(
            f"{path}: found legacy [forge.parameters] table. This forge.toml "
            "was written by a pre-Option forge; the current forge uses "
            "[forge.options] exclusively. Regenerate the project with the "
            "current forge to migrate."
        )

    version = str(forge.get("version", "0.0.0+unknown"))
    project_name = str(forge.get("project_name", ""))

    templates_tbl = forge.get("templates") or {}
    templates: dict[str, str] = {k: str(v) for k, v in dict(templates_tbl).items()}

    options_tbl = forge.get("options") or {}
    options: dict[str, Any] = _coerce_options(dict(options_tbl))

    provenance_tbl = forge.get("provenance") or {}
    provenance: dict[str, dict[str, str]] = {}
    for rel_path, entry in dict(provenance_tbl).items():
        if not isinstance(entry, dict):
            continue
        provenance[str(rel_path)] = {str(k): str(v) for k, v in dict(entry).items()}

    merge_blocks_tbl = forge.get("merge_blocks") or {}
    merge_blocks: dict[str, dict[str, str]] = {}
    for key, entry in dict(merge_blocks_tbl).items():
        if not isinstance(entry, dict):
            continue
        merge_blocks[str(key)] = {str(k): str(v) for k, v in dict(entry).items()}

    return ForgeTomlData(
        version=version,
        project_name=project_name,
        templates=templates,
        options=options,
        provenance=provenance,
        merge_blocks=merge_blocks,
    )


def _coerce_options(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the ``[forge.options]`` table into a plain dict.

    tomlkit returns its own wrappers (``Bool``, ``Integer``, ``String``,
    ``Array``); unwrap to native Python so downstream comparisons work.
    """
    out: dict[str, Any] = {}
    for key, value in raw.items():
        out[str(key)] = _unwrap(value)
    return out


def _unwrap(value: Any) -> Any:
    """Convert a tomlkit value to its native Python equivalent."""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_unwrap(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _unwrap(v) for k, v in value.items()}
    return value


def write_forge_toml(
    path: Path,
    *,
    version: str,
    project_name: str,
    templates: dict[str, str],
    options: dict[str, Any],
    provenance: dict[str, dict[str, str]] | None = None,
    merge_blocks: dict[str, dict[str, str]] | None = None,
) -> None:
    """Emit ``forge.toml`` with ``[forge.options]`` and (optional)
    ``[forge.provenance]`` + ``[forge.merge_blocks]`` sub-tables.

    ``merge_blocks`` stores per-block SHAs used by the three-way merge
    runtime (see ``forge/merge.py``) — one entry per ``merge``-zone
    injection that's been applied to the project.
    """
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Generated by forge — do not edit by hand."))
    doc.add(
        tomlkit.comment(
            "Re-render any subdirectory with `copier update` using its `.copier-answers.yml`."
        )
    )

    forge_tbl = tomlkit.table()
    forge_tbl.add("version", version)
    forge_tbl.add("project_name", project_name)

    tpl_tbl = tomlkit.table()
    for key in sorted(templates):
        tpl_tbl.add(key, templates[key])
    forge_tbl.add("templates", tpl_tbl)

    options_tbl = tomlkit.table()
    for key in sorted(options):
        options_tbl.add(key, options[key])
    forge_tbl.add("options", options_tbl)

    if provenance:
        prov_tbl = tomlkit.table()
        for rel_path in sorted(provenance):
            entry = provenance[rel_path]
            sub = tomlkit.table()
            for k in sorted(entry):
                sub.add(k, entry[k])
            prov_tbl.add(rel_path, sub)
        forge_tbl.add("provenance", prov_tbl)

    if merge_blocks:
        mb_tbl = tomlkit.table()
        for key in sorted(merge_blocks):
            entry = merge_blocks[key]
            sub = tomlkit.table()
            for k in sorted(entry):
                sub.add(k, entry[k])
            mb_tbl.add(key, sub)
        forge_tbl.add("merge_blocks", mb_tbl)

    doc.add("forge", forge_tbl)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")

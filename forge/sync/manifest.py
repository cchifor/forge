"""Read and write the project-root ``forge.toml`` manifest.

``forge.toml`` is the source of truth for ``forge --update``: it records
which forge version generated the project, where the templates live, and
every Option value the user set. From schema v2 (1.2.0+) it also
records per-language base-template versions, per-file template/fragment
versions, and per-block emitting-fragment metadata — the substrate the
bidirectional sync flows (forward update, reverse harvest, drift verify)
all share.

Canonical v2 format::

    [forge]
    schema_version = 2
    version = "1.2.0"
    project_name = "acme"

    [forge.templates]
    python = "services/python-service-template"

    [forge.template_versions]
    python = "0.6.1"

    [forge.options]
    "middleware.rate_limit" = true
    "rag.backend" = "qdrant"

    [forge.provenance."src/app/main.py"]
    origin = "base-template"
    sha256 = "abc..."
    template_name = "python-service-template"
    template_version = "0.6.1"
    emitted_at = "2026-04-21T14:33:02Z"

    [forge.merge_blocks."src/app/main.py::middleware_cors:MIDDLEWARE_REGISTRATION"]
    sha256 = "def..."
    fragment_name = "middleware_cors"
    fragment_version = "1.2.0"
    snippet_sha256 = "789..."
    line_range = [44, 46]

Schema v1 manifests (missing ``schema_version``) are accepted on read —
the new fields default to absent. The next ``forge --update`` run
upgrades the manifest in place via ``migrate_provenance_v2``.

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

CURRENT_SCHEMA_VERSION = 2


@dataclass
class ForgeTomlData:
    """Parsed ``forge.toml`` contents.

    ``schema_version`` reflects the manifest's encoding: 1 (legacy,
    pre-1.2.0) lacks the version+timestamp fields on per-file and
    per-block entries; 2 (1.2.0+) carries the richer metadata that
    enables drift verify and reverse-direction harvest. Manifests
    without an explicit version are interpreted as v1.
    """

    version: str
    project_name: str
    schema_version: int = CURRENT_SCHEMA_VERSION
    templates: dict[str, str] = field(default_factory=dict)
    # Per-language base-template semver at the time the project was
    # generated. Empty in v1 manifests. Populated in v2 from the
    # template's own version field at generate time.
    template_versions: dict[str, str] = field(default_factory=dict)
    # Dotted option path → value. Only paths the user explicitly set
    # appear here (the resolver fills in defaults).
    options: dict[str, Any] = field(default_factory=dict)
    # Per-path provenance for files the generator emitted. See
    # ``forge.sync.provenance`` for the recording / classification primitives.
    # Keys are POSIX-style relative paths; values are dicts whose keys
    # include ``{origin, sha256, fragment_name?, fragment_version?,
    # template_name?, template_version?, emitted_at?}``. v1 entries
    # carry only the first three.
    provenance: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Per-block baselines for merge-zone injections (1.0.0a3+).
    # Keys are ``{rel_path}::{feature_key}:{marker}``. Values include
    # ``{sha256, fragment_name?, fragment_version?, snippet_sha256?,
    # line_range?}``. v1 entries carry only ``{sha256}``.
    merge_blocks: dict[str, dict[str, Any]] = field(default_factory=dict)


def read_forge_toml(path: Path) -> ForgeTomlData:
    """Parse ``forge.toml`` into a structured object.

    Raises ``FileNotFoundError`` if the file is missing and ``ValueError``
    on malformed content or legacy-shape tables. Manifests without an
    explicit ``schema_version`` are interpreted as schema v1; the
    structure they expose has empty ``template_versions`` and
    sparse entry sub-dicts.
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

    # schema_version: absent → v1; integer → as-is.
    raw_schema = forge.get("schema_version")
    schema_version = int(raw_schema) if isinstance(raw_schema, int) else 1

    version = str(forge.get("version", "0.0.0+unknown"))
    project_name = str(forge.get("project_name", ""))

    templates_tbl = forge.get("templates") or {}
    templates: dict[str, str] = {k: str(v) for k, v in dict(templates_tbl).items()}

    template_versions_tbl = forge.get("template_versions") or {}
    template_versions: dict[str, str] = {k: str(v) for k, v in dict(template_versions_tbl).items()}

    options_tbl = forge.get("options") or {}
    options: dict[str, Any] = _coerce_options(dict(options_tbl))

    provenance_tbl = forge.get("provenance") or {}
    provenance: dict[str, dict[str, Any]] = {}
    for rel_path, entry in dict(provenance_tbl).items():
        if not isinstance(entry, dict):
            continue
        provenance[str(rel_path)] = _coerce_entry(dict(entry))

    merge_blocks_tbl = forge.get("merge_blocks") or {}
    merge_blocks: dict[str, dict[str, Any]] = {}
    for key, entry in dict(merge_blocks_tbl).items():
        if not isinstance(entry, dict):
            continue
        merge_blocks[str(key)] = _coerce_entry(dict(entry))

    return ForgeTomlData(
        version=version,
        project_name=project_name,
        schema_version=schema_version,
        templates=templates,
        template_versions=template_versions,
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


def _coerce_entry(raw: dict[str, Any]) -> dict[str, Any]:
    """Unwrap tomlkit values inside one provenance / merge_block entry.

    Keeps the dict-of-Any shape so callers see native Python types
    (str, int, list[int] for ``line_range``).
    """
    return {str(k): _unwrap(v) for k, v in raw.items()}


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
    provenance: dict[str, dict[str, Any]] | None = None,
    merge_blocks: dict[str, dict[str, Any]] | None = None,
    template_versions: dict[str, str] | None = None,
    schema_version: int = CURRENT_SCHEMA_VERSION,
) -> None:
    """Emit ``forge.toml`` with all v2 sub-tables.

    ``schema_version`` defaults to the current version; existing callers
    that omit it produce a v2 manifest. ``template_versions`` may be
    None or empty when the caller doesn't know per-template versions
    (legacy migration paths) — the table is omitted in that case.

    ``merge_blocks`` stores per-block metadata used by the three-way
    merge runtime (see :mod:`forge.sync.merge`) and by the
    reverse-direction harvester (see :mod:`forge.sync.project_to_forge`
    — Phase 4).
    """
    doc = tomlkit.document()
    doc.add(tomlkit.comment("Generated by forge — do not edit by hand."))
    doc.add(
        tomlkit.comment(
            "Re-render any subdirectory with `copier update` using its `.copier-answers.yml`."
        )
    )

    forge_tbl = tomlkit.table()
    forge_tbl.add("schema_version", schema_version)
    forge_tbl.add("version", version)
    forge_tbl.add("project_name", project_name)

    tpl_tbl = tomlkit.table()
    for key in sorted(templates):
        tpl_tbl.add(key, templates[key])
    forge_tbl.add("templates", tpl_tbl)

    if template_versions:
        tv_tbl = tomlkit.table()
        for key in sorted(template_versions):
            tv_tbl.add(key, template_versions[key])
        forge_tbl.add("template_versions", tv_tbl)

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

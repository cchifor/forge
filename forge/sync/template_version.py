"""Resolve and compare base-template versions.

A built-in (or plugin-registered) backend / frontend template's semver
is split across two sources:

* :attr:`forge.config.BackendSpec.version` / :attr:`FrontendSpec.version`
  — the typed default carried by the spec class. Bumped whenever the
  spec ships a new template version.
* ``_forge_template.toml`` (``[template].version``) — a forge-only
  metadata file shipped inside each template directory. When present it
  overrides the spec default, so template authors can iterate on a
  template version (and trigger ``forge --update``'s Copier re-render
  path) without editing the registry.

Resolution prefers the on-disk toml file; the spec value is the
fallback. Both are simple strings — we don't enforce semver structure
here (the comparison in the updater is string equality, not semver
ordering: any change to the recorded version triggers a re-render).

This module is intentionally small so the generator and the updater can
import it without dragging the rest of :mod:`forge.sync` along.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

TEMPLATE_METADATA_FILENAME = "_forge_template.toml"


def read_template_version(template_root: Path) -> str | None:
    """Return ``[template].version`` from ``_forge_template.toml`` if present.

    ``template_root`` is the directory containing ``copier.yml`` (e.g.
    ``forge/templates/services/python-service-template/``). Returns
    ``None`` when the metadata file is absent or malformed — callers
    fall back to the spec's typed default.
    """
    meta = template_root / TEMPLATE_METADATA_FILENAME
    if not meta.is_file():
        return None
    try:
        data = tomllib.loads(meta.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    section = data.get("template")
    if not isinstance(section, dict):
        return None
    version = section.get("version")
    if not isinstance(version, str):
        return None
    return version


def resolve_template_version(
    template_root: Path,
    *,
    spec_default: str,
) -> str:
    """Read the template's version, preferring the toml file.

    Falls back to ``spec_default`` (typically
    :attr:`BackendSpec.version` / :attr:`FrontendSpec.version`) when
    ``_forge_template.toml`` is missing or malformed.
    """
    on_disk = read_template_version(template_root)
    if on_disk is not None:
        return on_disk
    return spec_default

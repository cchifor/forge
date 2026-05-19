"""Sidecar discovery, parsing and classification.

Split out from the original ``resolver.py`` god module — see
:mod:`forge.sync.forge_to_project.resolver` for the public surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forge.fragments import MARKER_PREFIX
from forge.injectors.sentinels import _has_sentinel_block
from forge.sync.forge_to_project.resolver._shared import ResolveKind

_HEADER_TAG_PREFIX = "# forge merge conflict — tag: "
"""Prefix of the first line of a text sidecar (see ``merge.write_sidecar``)."""

# Length of the comment-style header written by write_sidecar /
# write_file_sidecar. The header is:
#
#   # forge merge conflict — tag: ...
#   # target: ...
#   #
#   # The block below is what forge wanted to write. Your current
#   # file contents differ from both this version AND the baseline
#   # forge last wrote, so the generator cannot safely pick a
#   # resolution. Merge by hand, then delete this sidecar.
#   <blank line>
#   <payload>
#
# That's 8 leading lines (7 comment + 1 blank). Keep this in sync with
# the sidecar writers — bumped only when the header layout changes.
_HEADER_LINES = 8


@dataclass(frozen=True)
class _ParsedSidecar:
    """Materialised form of one sidecar on disk.

    Used internally — :class:`ResolveEntry` is the public shape.
    """

    path: Path
    target: Path
    rel_sidecar: str
    rel_target: str
    tag: str
    is_binary: bool
    payload_text: str = ""
    payload_bytes: bytes = b""


def _discover_sidecars(project_root: Path) -> list[Path]:
    """Return every ``.forge-merge`` / ``.forge-merge.bin`` sidecar under root.

    Sorted by POSIX path so the resolve walk is deterministic across
    platforms. Mirrors the filter in
    :func:`forge.sync.forge_to_project.updater._count_file_sidecars` —
    only the two known sidecar suffixes count, not arbitrary user files.
    """
    if not project_root.is_dir():
        return []
    out: list[Path] = []
    for path in project_root.rglob("*.forge-merge*"):
        if not path.is_file():
            continue
        if path.name.endswith(".forge-merge") or path.name.endswith(".forge-merge.bin"):
            out.append(path)
    out.sort(key=lambda p: p.as_posix())
    return out


def _target_for_sidecar(sidecar: Path) -> Path:
    """Strip the ``.forge-merge[.bin]`` suffix to recover the target path.

    The sidecar writer appends ``.forge-merge`` (text) or
    ``.forge-merge.bin`` (binary) to the target's name — see
    :func:`forge.sync.merge.write_sidecar` /
    :func:`forge.sync.merge.write_file_sidecar`. Inverse here.
    """
    name = sidecar.name
    if name.endswith(".forge-merge.bin"):
        bare = name[: -len(".forge-merge.bin")]
    elif name.endswith(".forge-merge"):
        bare = name[: -len(".forge-merge")]
    else:
        bare = name
    return sidecar.with_name(bare)


def _parse_sidecar(sidecar: Path, project_root: Path) -> _ParsedSidecar | None:
    """Read the sidecar from disk + parse its header tag.

    Returns ``None`` when the sidecar is unreadable. Binary sidecars
    (``.forge-merge.bin``) have no header — we synthesise a tag from
    the target's relative path so the classifier still has something
    to key on.
    """
    target = _target_for_sidecar(sidecar)
    rel_sidecar = _safe_relpath(sidecar, project_root)
    rel_target = _safe_relpath(target, project_root)

    if sidecar.name.endswith(".forge-merge.bin"):
        try:
            payload_bytes = sidecar.read_bytes()
        except OSError:
            return None
        return _ParsedSidecar(
            path=sidecar,
            target=target,
            rel_sidecar=rel_sidecar,
            rel_target=rel_target,
            tag=f"binary:{rel_target}",
            is_binary=True,
            payload_bytes=payload_bytes,
        )

    try:
        text = sidecar.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    tag = _extract_tag(text)
    payload = _strip_header(text)
    return _ParsedSidecar(
        path=sidecar,
        target=target,
        rel_sidecar=rel_sidecar,
        rel_target=rel_target,
        tag=tag,
        is_binary=False,
        payload_text=payload,
    )


def _extract_tag(sidecar_text: str) -> str:
    """Pull the tag out of the first header line.

    The header is written by :func:`forge.sync.merge.write_sidecar` /
    :func:`forge.sync.merge.write_file_sidecar` with a fixed first
    line:

        # forge merge conflict — tag: <tag>

    Returns an empty string when the line doesn't match — defensive,
    so a hand-edited sidecar still flows through resolution.
    """
    first_newline = sidecar_text.find("\n")
    first_line = sidecar_text[:first_newline] if first_newline != -1 else sidecar_text
    if first_line.startswith(_HEADER_TAG_PREFIX):
        return first_line[len(_HEADER_TAG_PREFIX) :].strip()
    return ""


def _strip_header(sidecar_text: str) -> str:
    """Return the payload (post-header) portion of the sidecar's content.

    The writers always emit ``_HEADER_LINES`` leading lines (7 comment
    + 1 blank separator). Anything beyond that is the payload — the
    block body for block-level, or the full file content for
    file-level.

    If the sidecar has been hand-edited and lost its header, we fall
    back to the full body — better to apply something the user can
    visually inspect than to silently lose payload.
    """
    lines = sidecar_text.splitlines(keepends=True)
    if len(lines) < _HEADER_LINES:
        return sidecar_text
    if not lines[0].startswith(_HEADER_TAG_PREFIX):
        return sidecar_text
    return "".join(lines[_HEADER_LINES:])


def _safe_relpath(p: Path, root: Path) -> str:
    """POSIX relative path; falls back to ``p.name`` when outside root.

    The sidecar walk never produces paths outside the project root in
    practice, but ``Path.relative_to`` raises ``ValueError`` for
    that case; the fallback keeps the report renderable.
    """
    try:
        return p.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return p.name


def _classify_sidecar(parsed: _ParsedSidecar) -> tuple[ResolveKind, str, str]:
    """Decide whether to apply a sidecar block-style or file-style.

    Returns ``(kind, feature_key, marker)``. For ``file`` / ``binary-file``
    the second + third elements are empty strings (those resolutions
    don't need a marker pair).

    Heuristic: the block-level tag format is ``<feature_key>:<MARKER>``
    where ``MARKER`` is the bare marker name (no ``FORGE:`` prefix).
    The file-level tag format is ``<fragment_name>:<rel/path>``, where
    the path contains a ``/`` or ``.`` — those characters wouldn't
    appear in a bare marker. We use that distinction plus the presence
    of a matching BEGIN/END sentinel pair in the target as the
    definitive signal: a tag whose pair is in the file IS block-level,
    everything else IS file-level.

    This is robust to a fragment author choosing a marker name that
    happens to look path-like — we check the target before deciding.
    """
    if parsed.is_binary:
        return "binary-file", "", ""

    # Try parsing as block-level first. The tag has the form
    # "<feature_key>:<MARKER_BARE>" and the target should carry a
    # FORGE:BEGIN ... <tag> sentinel for it.
    tag = parsed.tag
    if ":" in tag:
        feature_key, marker_bare = tag.split(":", 1)
        # Block-level markers are bare identifiers — no path
        # separators. File-level tags have a rel-path on the RHS, so
        # they contain "/" (POSIX-normalised) or "\\" (Windows) or
        # a "." (extension).
        looks_like_marker = (
            "/" not in marker_bare and "\\" not in marker_bare and "." not in marker_bare
        )
        if looks_like_marker and parsed.target.is_file():
            marker_full = f"{MARKER_PREFIX}{marker_bare}"
            if _has_sentinel_block(parsed.target, feature_key, marker_full):
                return "block", feature_key, marker_full

    # Fall through — file-level (text). Binary already returned above.
    return "file", "", ""

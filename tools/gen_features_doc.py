"""Regenerate the auto-section of ``docs/FEATURES.md`` from ``OPTION_REGISTRY``.

The catalog block in ``docs/FEATURES.md`` (delimited by the BEGIN /
END markers below) is the canonical per-option reference for built-in
forge features. It is generated from the live ``OPTION_REGISTRY`` —
*do not hand-edit it*; edit the option in ``forge/features/<ns>/options.py``
and rerun this script. The CI gate at
``tests/test_features_doc_in_sync.py`` enforces this invariant.

Usage::

    uv run python tools/gen_features_doc.py            # rewrite the file
    uv run python tools/gen_features_doc.py --check    # exit non-zero if drift

This is intentionally a standalone script, not a CLI verb. Importing
``forge.options`` runs every built-in feature's ``register_option``
call but does NOT trigger ``forge.plugins.load_all`` — so plugin
options are absent from the output. That is correct: the bundled
FEATURES.md describes the built-in surface only; plugin authors
ship their own equivalent under their own package.

Layer-mode options (``backend.mode``, ``database.mode``,
``database.engine``, ``frontend.mode``, ``frontend.api_target.*``,
``agent.mode``) are excluded because they're documented separately
in the hand-written "Layer discriminators" section of FEATURES.md
— their semantics (orchestration knobs, no ``enables`` map) don't
fit the per-category capability table format.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Importing forge.options runs the built-in registrations.
# IMPORTANT: do NOT import forge.cli or forge.plugins from here — that
# would trigger plugin discovery and pollute OPTION_REGISTRY with
# non-built-in entries.
from forge.options import (
    CATEGORY_DISPLAY,
    CATEGORY_MISSION,
    CATEGORY_ORDER,
    OPTION_REGISTRY,
    Option,
    OptionType,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FEATURES_DOC = REPO_ROOT / "docs" / "FEATURES.md"

BEGIN_MARKER = (
    "<!-- BEGIN GENERATED:OPTIONS-CATALOG — "
    "do not hand-edit. Regenerate with: "
    "uv run python tools/gen_features_doc.py -->"
)
END_MARKER = "<!-- END GENERATED:OPTIONS-CATALOG -->"


# Paths excluded from the auto-catalog (documented in the hand-written
# "Layer discriminators" section instead).
def _is_layer_option(option: Option) -> bool:
    if option.path.endswith(".mode"):
        return True
    if option.path.startswith("frontend.api_target"):
        return True
    if option.path == "database.engine":
        return True
    return False


def _backends_for(option: Option) -> list[str]:
    """Per-backend support list, computed from fragments the option enables.

    For options without an ``enables`` map (STR / INT / LIST whose value
    is read directly into template context), the support set is empty —
    surface as ``—``.
    """
    from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415

    backends: set[str] = set()
    for fragment_names in option.enables.values():
        for name in fragment_names:
            frag = FRAGMENT_REGISTRY.get(name)
            if frag is None:
                continue
            for lang in frag.implementations:
                backends.add(lang.value)
    return sorted(backends)


def _format_default(option: Option) -> str:
    if option.type is OptionType.BOOL:
        return f"`{str(option.default).lower()}`"
    if option.type is OptionType.STR and option.default == "":
        return '`""`'
    return f"`{option.default}`"


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return f"`{str(value).lower()}`"
    return f"`{value}`"


def render_option_section(opt: Option) -> str:
    """Render one option as a markdown subsection."""
    backends = _backends_for(opt)
    backends_str = ", ".join(backends) if backends else "—"

    lines: list[str] = []
    lines.append(f"### `{opt.path}`")
    lines.append("")
    metadata_bits = [
        f"**Type:** `{opt.type.value}`",
        f"**Default:** {_format_default(opt)}",
        f"**Stability:** `{opt.stability}`",
        f"**Backends:** {backends_str}",
    ]
    lines.append(" · ".join(metadata_bits))

    if opt.type is OptionType.ENUM and opt.options:
        allowed = ", ".join(_format_value(v) for v in opt.options)
        lines.append("")
        lines.append(f"**Allowed values:** {allowed}")

    if opt.type is OptionType.INT and (opt.min is not None or opt.max is not None):
        bounds = []
        if opt.min is not None:
            bounds.append(f"min `{opt.min}`")
        if opt.max is not None:
            bounds.append(f"max `{opt.max}`")
        lines.append("")
        lines.append(f"**Bounds:** {', '.join(bounds)}")

    if opt.summary:
        lines.append("")
        lines.append(f"_{opt.summary.strip()}_")

    if opt.description and opt.description.strip() != opt.summary.strip():
        lines.append("")
        lines.append(opt.description.strip())

    if opt.enables:
        lines.append("")
        lines.append("**Enables fragments:**")
        for value, fragments in opt.enables.items():
            value_str = _format_value(value)
            frags = ", ".join(f"`{f}`" for f in fragments)
            if not fragments:
                continue
            lines.append(f"- on {value_str} → {frags}")

    if opt.aliases:
        lines.append("")
        aliases_str = ", ".join(f"`{a}`" for a in opt.aliases)
        suffix = f" (since {opt.deprecated_since})" if opt.deprecated_since else ""
        lines.append(f"**Deprecated aliases{suffix}:** {aliases_str}")

    return "\n".join(lines)


def render_catalog() -> str:
    """Render the full catalog body (between the markers)."""
    by_cat: dict = {}
    for opt in OPTION_REGISTRY.values():
        if _is_layer_option(opt):
            continue
        if opt.hidden:
            continue
        by_cat.setdefault(opt.category, []).append(opt)

    blocks: list[str] = [
        "",
        "Options are grouped by `FeatureCategory` — same order `forge --list`",
        "prints. Run `forge --describe <path>` for the full prose plus tag",
        "lines (`BACKENDS:` / `ENDPOINTS:` / `REQUIRES:`) of any single",
        "option. The CLI is the runtime SSoT and is plugin-aware; this",
        "catalog covers built-in options only. Layer-discriminator options",
        "(`backend.mode`, `database.mode`, `frontend.mode`,",
        "`frontend.api_target.*`, `agent.mode`) are documented in the",
        "hand-written section below.",
        "",
    ]

    for cat in CATEGORY_ORDER:
        opts = sorted(by_cat.get(cat, []), key=lambda o: o.path)
        if not opts:
            continue
        display = CATEGORY_DISPLAY[cat]
        mission = CATEGORY_MISSION[cat]
        blocks.append(f"## {display}")
        blocks.append("")
        blocks.append(f"_{mission}_")
        blocks.append("")
        for opt in opts:
            blocks.append(render_option_section(opt))
            blocks.append("")

    return "\n".join(blocks).rstrip() + "\n"


_MARKER_RE = re.compile(
    re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
    re.DOTALL,
)


def replace_in_features_doc(content: str, generated: str) -> str:
    """Replace the BEGIN..END block with the freshly-generated content."""
    replacement = f"{BEGIN_MARKER}\n{generated}\n{END_MARKER}"
    if not _MARKER_RE.search(content):
        raise SystemExit(
            f"Could not find BEGIN/END markers in {FEATURES_DOC}.\n"
            "Add these around the auto-generated section:\n"
            f"  {BEGIN_MARKER}\n"
            f"  ... generated content here ...\n"
            f"  {END_MARKER}"
        )
    return _MARKER_RE.sub(replacement, content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if FEATURES.md would change. Used by CI.",
    )
    args = parser.parse_args(argv)

    current = FEATURES_DOC.read_text(encoding="utf-8")
    generated = render_catalog()
    updated = replace_in_features_doc(current, generated)

    if args.check:
        if current != updated:
            print(
                f"{FEATURES_DOC} is out of sync with OPTION_REGISTRY.",
                file=sys.stderr,
            )
            print(
                "Regenerate with: uv run python tools/gen_features_doc.py",
                file=sys.stderr,
            )
            return 1
        return 0

    if current == updated:
        print(f"{FEATURES_DOC} already in sync.")
        return 0

    FEATURES_DOC.write_text(updated, encoding="utf-8")
    print(f"Wrote {FEATURES_DOC}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

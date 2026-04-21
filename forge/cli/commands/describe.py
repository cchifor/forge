"""`forge --describe PATH` — print the full description block for one Option."""

from __future__ import annotations

import sys

from forge.cli.commands.list import _option_backends, _option_parity_tier
from forge.options import CATEGORY_DISPLAY, OPTION_REGISTRY, OptionType


def _describe_option(path: str) -> None:
    """Print the full description block for one Option path and exit.

    Close-match suggestion covers typos ("rag_backend" -> "rag.backend").
    """
    opt = OPTION_REGISTRY.get(path)
    if opt is None:
        import difflib  # noqa: PLC0415

        matches = difflib.get_close_matches(path, list(OPTION_REGISTRY), n=3, cutoff=0.5)
        suggestion = f" Did you mean: {', '.join(matches)}?" if matches else ""
        print(f"Unknown option {path!r}.{suggestion}", file=sys.stderr)
        sys.exit(1)

    backends = ", ".join(_option_backends(opt)) or "—"
    category = CATEGORY_DISPLAY[opt.category]
    tier = _option_parity_tier(opt)
    tier_label = {
        1: "1 (all built-in backends)",
        2: "2 (best-effort)",
        3: "3 (python-only)",
    }.get(tier, str(tier))

    print(f"{opt.path}  [{opt.type.value}]")
    print(f"Category: {category}")
    parts = [
        f"Default: {opt.default}",
        f"Stability: {opt.stability}",
        f"Parity: {tier_label}",
        f"Backends: {backends}",
    ]
    print("    ".join(parts))
    if opt.options:
        print(f"Allowed:  {', '.join(str(v) for v in opt.options)}")
    if opt.min is not None or opt.max is not None:
        bounds = []
        if opt.min is not None:
            bounds.append(f"min={opt.min}")
        if opt.max is not None:
            bounds.append(f"max={opt.max}")
        print(f"Bounds:   {', '.join(bounds)}")
    if opt.pattern is not None:
        print(f"Pattern:  {opt.pattern}")
    if opt.enables:
        print()
        print("Per-value fragment enables:")
        if opt.type is OptionType.BOOL:
            for val in (True, False):
                fragments = opt.enables.get(val, ())
                if fragments:
                    print(f"  {str(val):<12} -> {', '.join(fragments)}")
        else:
            for val in opt.options:
                fragments = opt.enables.get(val, ())
                if fragments:
                    print(f"  {str(val):<12} -> {', '.join(fragments)}")
                else:
                    print(f"  {str(val):<12} -> (no fragments)")
    print()
    print(opt.description or "(no description)")
    sys.exit(0)

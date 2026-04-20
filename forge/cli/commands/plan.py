"""`forge --plan` — resolve the config and preview the generation plan.

Prints the ordered fragment list with dependencies, target backends,
capability sets, and (when a config file is provided) the full tree of
files and injections that would be written to disk — without touching
the filesystem.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from forge.capability_resolver import resolve
from forge.cli.builder import _build_config
from forge.cli.loader import _load_config_file


def _dispatch_plan(args: argparse.Namespace) -> None:
    """Build a plan preview and print it, then exit."""
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

    plan = resolve(config)
    preview = _build_preview(config, plan)

    if getattr(args, "json_output", False):
        sys.stdout.write(json.dumps(preview, indent=2, default=str) + "\n")
    else:
        _print_tree(preview)
    sys.exit(0)


def _build_preview(config, plan) -> dict[str, Any]:
    """Structured preview consumable by JSON mode or the tree printer."""
    from forge.feature_injector import FRAGMENTS_DIR  # noqa: PLC0415

    backends = [
        {
            "name": bc.name,
            "language": bc.language.value,
            "port": bc.server_port,
            "features": list(bc.features),
        }
        for bc in config.backends
    ]

    fragments: list[dict[str, Any]] = []
    for rf in plan.ordered:
        frag = rf.fragment
        per_backend_files: dict[str, list[str]] = {}
        per_backend_injections: dict[str, list[dict[str, str]]] = {}
        for lang in rf.target_backends:
            impl = frag.implementations[lang]
            from forge.feature_injector import _resolve_fragment_dir  # noqa: PLC0415

            fragment_dir = _resolve_fragment_dir(impl.fragment_dir)
            files_dir = fragment_dir / "files"
            files: list[str] = []
            if files_dir.is_dir():
                files = sorted(
                    [
                        str(p.relative_to(files_dir).as_posix())
                        for p in files_dir.rglob("*")
                        if p.is_file()
                    ]
                )
            per_backend_files[lang.value] = files

            inject_path = fragment_dir / "inject.yaml"
            injections: list[dict[str, str]] = []
            if inject_path.is_file():
                import yaml  # noqa: PLC0415

                data = yaml.safe_load(inject_path.read_text(encoding="utf-8")) or []
                if isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict):
                            injections.append(
                                {
                                    "target": str(entry.get("target", "")),
                                    "marker": str(entry.get("marker", "")),
                                    "position": str(entry.get("position", "after")),
                                }
                            )
            per_backend_injections[lang.value] = injections

        fragments.append(
            {
                "name": frag.name,
                "target_backends": [lang.value for lang in rf.target_backends],
                "capabilities": sorted(frag.capabilities),
                "depends_on": list(frag.depends_on),
                "files_by_backend": per_backend_files,
                "injections_by_backend": per_backend_injections,
            }
        )

    return {
        "project_name": config.project_name,
        "output_dir": config.output_dir,
        "backends": backends,
        "frontend": (
            config.frontend.framework.value
            if config.frontend and config.frontend.framework.value != "none"
            else None
        ),
        "capabilities": sorted(plan.capabilities),
        "option_values": dict(plan.option_values),
        "fragments": fragments,
    }


def _print_tree(preview: dict[str, Any]) -> None:
    """Human-readable tree rendering of a plan preview.

    Uses pure ASCII glyphs so Windows ``cp1252`` consoles don't choke
    (Python's default stream encoding can't handle U+2500-U+2BFF box
    drawing). A Unicode variant can come back once we optionally
    reconfigure stdout to UTF-8, but ASCII is the safe floor.
    """

    def _w(s: str) -> None:
        try:
            sys.stdout.write(s)
        except UnicodeEncodeError:
            # Final safety net for any exotic char that slipped through.
            sys.stdout.write(s.encode("ascii", errors="replace").decode("ascii"))

    _w(f"forge plan  .  project={preview['project_name']}\n")
    _w(f"output    : {preview['output_dir']}\n")
    backends_line = (
        ", ".join(
            bc["name"] + " (" + bc["language"] + ")" for bc in preview["backends"]
        )
        or "(none)"
    )
    _w(f"backends  : {backends_line}\n")
    _w(f"frontend  : {preview['frontend'] or '(none)'}\n")
    _w(f"caps      : {', '.join(preview['capabilities']) or '(none)'}\n")
    _w(f"fragments : {len(preview['fragments'])}\n")
    _w("\n")

    if not preview["fragments"]:
        _w("  (no fragments to apply -- all options left at defaults or disabled)\n")
        return

    for i, frag in enumerate(preview["fragments"], 1):
        is_last = i == len(preview["fragments"])
        branch = "`-- " if is_last else "|-- "
        _w(f"{branch}{frag['name']}  -> {', '.join(frag['target_backends'])}\n")
        vbar = "    " if is_last else "|   "

        if frag["depends_on"]:
            _w(f"{vbar}  depends_on: {', '.join(frag['depends_on'])}\n")
        if frag["capabilities"]:
            _w(f"{vbar}  capabilities: {', '.join(frag['capabilities'])}\n")

        for lang, files in frag["files_by_backend"].items():
            injections = frag["injections_by_backend"].get(lang, [])
            if not files and not injections:
                continue
            _w(f"{vbar}  [{lang}]\n")
            for f in files:
                _w(f"{vbar}    + {f}\n")
            for inj in injections:
                _w(f"{vbar}    ~ {inj['target']}  (at {inj['marker']}, {inj['position']})\n")
        _w("\n")

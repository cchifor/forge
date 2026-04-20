"""`forge --plugins list` — enumerate loaded and failed plugins."""

from __future__ import annotations

import json
import sys


def _dispatch_plugins(subcommand: str, *, json_output: bool = False) -> None:
    """Dispatch a plugins subcommand and exit."""
    from forge import plugins  # noqa: PLC0415

    # Ensure plugins are discovered even if main() hasn't called load_all yet.
    plugins.load_all()

    if subcommand == "list":
        _list_plugins(json_output=json_output)
        sys.exit(0)

    print(f"Unknown plugins subcommand: {subcommand}", file=sys.stderr)
    sys.exit(1)


def _list_plugins(*, json_output: bool = False) -> None:
    from forge import plugins  # noqa: PLC0415

    if json_output:
        payload = {
            "loaded": [reg.as_dict() for reg in plugins.LOADED_PLUGINS],
            "failed": [{"name": n, "error": e} for n, e in plugins.FAILED_PLUGINS],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return

    loaded = plugins.LOADED_PLUGINS
    failed = plugins.FAILED_PLUGINS

    if not loaded and not failed:
        print("No forge plugins installed.")
        print("Install one with: pip install forge-plugin-<name>")
        print("See: docs/plugin-development.md")
        return

    if loaded:
        print(f"Loaded plugins ({len(loaded)}):")
        for reg in loaded:
            ver = f" v{reg.version}" if reg.version else ""
            print(f"  * {reg.name}{ver}  ({reg.module})")
            parts = []
            if reg.options_added:
                parts.append(f"{reg.options_added} option(s)")
            if reg.fragments_added:
                parts.append(f"{reg.fragments_added} fragment(s)")
            if reg.backends_added:
                parts.append(f"{reg.backends_added} backend(s)")
            if reg.commands_added:
                parts.append(f"{reg.commands_added} command(s)")
            if reg.emitters_added:
                parts.append(f"{reg.emitters_added} emitter(s)")
            if parts:
                print(f"      adds: {', '.join(parts)}")

    if failed:
        print()
        print(f"Failed plugins ({len(failed)}):")
        for name, err in failed:
            print(f"  ! {name}: {err}")

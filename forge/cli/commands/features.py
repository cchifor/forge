"""`forge --features-cmd ...` — feature management subcommands.

Subcommands:

* ``list`` — enumerate all discovered features with metadata from manifests.
* ``deps`` — show the dependency tree for a named feature.
* ``validate`` — parse all manifests and check contracts against registries.
* ``scaffold`` — render a skeleton feature directory with feature.toml,
  __init__.py, options.py, fragments.py, and templates/.
"""

from __future__ import annotations

import json
import keyword
import sys
from pathlib import Path


def _dispatch_features(
    subcommand: str,
    *,
    json_output: bool = False,
    name: str | None = None,
) -> None:
    """Dispatch a features subcommand and exit."""
    if subcommand == "list":
        _list_features(json_output=json_output)
        sys.exit(0)

    if subcommand == "deps":
        if not name:
            print(
                "deps requires a feature name: `forge --features-cmd deps --features-name <NAME>`",
                file=sys.stderr,
            )
            sys.exit(2)
        _deps_feature(name)
        sys.exit(0)

    if subcommand == "validate":
        _validate_features(json_output=json_output)
        sys.exit(0)

    if subcommand == "scaffold":
        if not name:
            print(
                "scaffold requires a feature name: "
                "`forge --features-cmd scaffold --features-name <NAME>`",
                file=sys.stderr,
            )
            sys.exit(2)
        _scaffold_feature(name)
        sys.exit(0)

    print(f"Unknown features subcommand: {subcommand!r}", file=sys.stderr)
    sys.exit(2)


# ------------------------------------------------------------------
# list
# ------------------------------------------------------------------


def _list_features(*, json_output: bool = False) -> None:
    from forge.feature_loader import LOADED_FEATURES  # noqa: PLC0415

    if json_output:
        data = [
            {
                "name": m.name,
                "version": m.version,
                "summary": m.summary,
                "category": m.category,
                "depends": list(m.depends.keys()),
                "options_count": len(m.provides_options),
                "fragments_count": len(m.provides_fragments),
            }
            for m in LOADED_FEATURES
        ]
        print(json.dumps(data, indent=2))
        return

    if not LOADED_FEATURES:
        print("No features loaded.")
        return

    max_name = max(len(m.name) for m in LOADED_FEATURES)
    max_ver = max(len(m.version) for m in LOADED_FEATURES)
    max_cat = max(len(m.category) for m in LOADED_FEATURES)

    for m in sorted(LOADED_FEATURES, key=lambda x: x.name):
        deps = f"  deps: {', '.join(m.depends)}" if m.depends else ""
        print(
            f"  {m.name:<{max_name}}  {m.version:<{max_ver}}  "
            f"{m.category:<{max_cat}}  {m.summary}{deps}"
        )


# ------------------------------------------------------------------
# deps
# ------------------------------------------------------------------


def _deps_feature(name: str) -> None:
    from forge.feature_loader import LOADED_FEATURES  # noqa: PLC0415

    by_name = {m.name: m for m in LOADED_FEATURES}
    if name not in by_name:
        print(f"Feature {name!r} not found.", file=sys.stderr)
        sys.exit(2)

    manifest = by_name[name]
    print(f"  {manifest.name}")
    deps = list(manifest.depends.keys())
    for i, dep in enumerate(deps):
        prefix = "└── " if i == len(deps) - 1 else "├── "
        dep_manifest = by_name.get(dep)
        if dep_manifest:
            frags = ", ".join(dep_manifest.provides_fragments[:3])
            suffix = f" (provides: {frags})"
        else:
            suffix = " (not found)"
        print(f"  {prefix}{dep}{suffix}")

    if not deps:
        print("  (no dependencies)")


# ------------------------------------------------------------------
# validate
# ------------------------------------------------------------------


def _validate_features(*, json_output: bool = False) -> None:
    from forge.feature_loader import LOADED_FEATURES  # noqa: PLC0415
    from forge.feature_manifest import validate_manifest_contracts  # noqa: PLC0415
    from forge.fragments import FRAGMENT_REGISTRY  # noqa: PLC0415
    from forge.options._registry import OPTION_REGISTRY  # noqa: PLC0415

    registered_options = frozenset(OPTION_REGISTRY.keys())
    registered_fragments = frozenset(FRAGMENT_REGISTRY.keys())

    all_errors: dict[str, list[str]] = {}
    for manifest in LOADED_FEATURES:
        violations = validate_manifest_contracts(
            manifest,
            registered_options,
            registered_fragments,
        )
        if violations:
            all_errors[manifest.name] = violations

    if json_output:
        print(json.dumps(all_errors, indent=2))
        if all_errors:
            sys.exit(1)
        return

    if all_errors:
        for feature_name, errors in all_errors.items():
            for err in errors:
                print(f"  ERROR ({feature_name}): {err}", file=sys.stderr)
        total = sum(len(e) for e in all_errors.values())
        print(
            f"\n  {len(LOADED_FEATURES)} features loaded, "
            f"{total} errors in {len(all_errors)} features",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print(f"  {len(LOADED_FEATURES)} features loaded, 0 errors.")


# ------------------------------------------------------------------
# scaffold
# ------------------------------------------------------------------


def _scaffold_feature(name: str) -> None:
    if not name.isidentifier() or keyword.iskeyword(name):
        print(f"{name!r} is not a valid Python identifier.", file=sys.stderr)
        sys.exit(2)

    features_dir = Path(__file__).resolve().parent.parent.parent / "features"
    target = features_dir / name

    if target.exists():
        print(f"Feature directory already exists: {target}", file=sys.stderr)
        sys.exit(2)

    target.mkdir(parents=True)
    (target / "templates").mkdir()

    (target / "feature.toml").write_text(
        f"""[feature]
name = "{name}"
version = "1.0.0"
summary = "TODO: describe this feature."
category = "platform"

[feature.depends]

[feature.provides]
options = ["{name}.enabled"]
fragments = ["{name}_core"]
""",
        encoding="utf-8",
    )

    (target / "__init__.py").write_text(
        f'''"""{name} feature."""
from __future__ import annotations
from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.{name} import options, fragments
    options.register_all(api)
    fragments.register_all(api)
''',
        encoding="utf-8",
    )

    (target / "options.py").write_text(
        f'''"""{name} options."""
from __future__ import annotations

from forge.api import ForgeAPI
from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
)


def register_all(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="{name}.enabled",
            type=OptionType.BOOL,
            default=False,
            summary="Enable the {name} feature.",
            category=FeatureCategory.PLATFORM,
            enables={{True: ("{name}_core",)}},
        )
    )
''',
        encoding="utf-8",
    )

    (target / "fragments.py").write_text(
        f'''"""{name} fragments."""
from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(fragment: str, lang: str) -> str:
    return str(_TEMPLATES / fragment / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="{name}_core",
            implementations={{
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("{name}_core", "python"),
                ),
            }},
        )
    )
''',
        encoding="utf-8",
    )

    print(f"  Created forge/features/{name}/")
    print("  ├── feature.toml")
    print("  ├── __init__.py")
    print("  ├── options.py")
    print("  ├── fragments.py")
    print("  └── templates/")
    print()
    print("  Next: edit feature.toml, options.py, and fragments.py to define your feature.")

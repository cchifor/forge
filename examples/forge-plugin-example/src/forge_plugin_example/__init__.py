"""Reference forge plugin — adds the ``example.hello_banner`` option.

When enabled, the generated Python backend prints "hello from forge-plugin-example"
to stderr at startup. Demonstrates option → fragment wiring for plugin authors.

User-visible metadata (summary, description, category, stability) lives
on the ``Option`` — the ``Fragment`` itself is implementation-only. See
``forge.fragments.Fragment`` for the current shape.

Fragment directories ship inside this package and are passed as absolute
paths (``Path(__file__).parent / "fragments" / ...``). Built-in forge
fragments live under ``forge/templates/_fragments/`` and are referenced
by relative path; plugins must use absolute paths because forge can't
guess where the plugin's package lives on disk.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments import Fragment, FragmentImplSpec
from forge.options import FeatureCategory, Option, OptionType

_PACKAGE_ROOT = Path(__file__).resolve().parent
_FRAGMENT_ROOT = _PACKAGE_ROOT / "fragments"


def register(api: ForgeAPI) -> None:
    api.add_option(
        Option(
            path="example.hello_banner",
            type=OptionType.BOOL,
            category=FeatureCategory.PLATFORM,
            default=False,
            summary="Print a hello banner at startup (reference plugin)",
            description=(
                "When enabled, the generated Python backend prints "
                "'hello from forge-plugin-example' to stderr at startup. "
                "Demonstrates option → fragment wiring for plugin authors."
            ),
            enables={True: ("example_hello_banner",)},
        )
    )

    api.add_fragment(
        Fragment(
            name="example_hello_banner",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=str(_FRAGMENT_ROOT / "hello_banner" / "python"),
                    dependencies=(),
                    env_vars=(),
                ),
            },
        )
    )

"""Reference forge plugin — adds the ``example.hello_banner`` option.

When enabled, the generated Python backend prints "hello from forge-plugin-example"
to stderr at startup. Demonstrates option → fragment wiring for plugin authors.
"""

from __future__ import annotations

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments import Fragment, FragmentImplSpec
from forge.options import FeatureCategory, Option, OptionType


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
                "'hello from forge-plugin-example' to stderr on every request. "
                "Demonstrates option → fragment wiring for plugin authors."
            ),
            enables={True: ("example_hello_banner",)},
        )
    )

    api.add_fragment(
        Fragment(
            name="example_hello_banner",
            category=FeatureCategory.PLATFORM,
            summary="Print a hello banner at startup",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir="forge_plugin_example/fragments/hello_banner/python",
                    dependencies=(),
                    env_vars=(),
                ),
            },
            capabilities=frozenset(),
        )
    )

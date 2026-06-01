"""WS-3.3(c): forge.api must declare its documented stable surface in __all__.

The module docstring advertises a "Stable Public API" table, but until now
``__all__`` did not exist — so ``from forge.api import *`` and tooling that
introspects the public surface had nothing authoritative to read. These
tests pin the surface and snapshot it so a breaking removal is caught.
"""

from __future__ import annotations

import forge.api as api


EXPECTED_ALL = (
    "ForgeAPI",
    "PluginRegistration",
    "PluginExtractorRegistration",
    "PluginOptionRegistration",
    "PluginEmitterRegistration",
    "SDK_VERSION",
)


def test_all_is_defined_and_is_a_tuple():
    assert hasattr(api, "__all__"), "forge.api must declare __all__"
    assert isinstance(api.__all__, tuple), "__all__ should be a tuple (immutable surface)"


def test_all_names_resolve():
    for name in api.__all__:
        assert hasattr(api, name), f"__all__ lists {name!r} but forge.api has no such attribute"


def test_all_matches_documented_surface_snapshot():
    # Snapshot: the public surface is stable. Adding a name is a deliberate
    # edit here + a docs/SDK_CHANGELOG.md entry; removing one is a major bump.
    assert set(api.__all__) == set(EXPECTED_ALL), (
        "forge.api.__all__ drifted from the documented stable surface; "
        "update the docstring table + docs/SDK_CHANGELOG.md if intentional"
    )

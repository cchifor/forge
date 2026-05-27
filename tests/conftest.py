"""Shared pytest fixtures / configuration for the forge test suite.

Epic S (1.1.0-alpha.1): filter the DeprecationWarning from the
``forge.errors.GeneratorError`` alias so the test suite doesn't drown
in noise while the in-repo uses are being migrated. Tests that
specifically assert the deprecation behavior (see
``tests/test_errors.py::TestDeprecatedGeneratorError``) use
``warnings.catch_warnings()`` to temporarily unsilence the filter.
"""

from __future__ import annotations

import warnings

import pytest


def pytest_configure(config):  # noqa: ARG001
    warnings.filterwarnings(
        "ignore",
        message=r".*forge\.errors\.GeneratorError is deprecated.*",
        category=DeprecationWarning,
    )


@pytest.fixture(scope="session", autouse=True)
def _load_features():
    """Populate registries at session start, mirroring CLI startup.

    Features are no longer eagerly loaded at ``import forge`` time;
    the CLI calls ``feature_loader.load_all()`` before parsing args.
    Tests need the same initialization.
    """
    from forge import feature_loader

    feature_loader.load_all()

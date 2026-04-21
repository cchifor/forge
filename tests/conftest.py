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


def pytest_configure(config):  # noqa: ARG001
    warnings.filterwarnings(
        "ignore",
        message=r".*forge\.errors\.GeneratorError is deprecated.*",
        category=DeprecationWarning,
    )

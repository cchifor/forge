"""Fixtures for the pre-ownership update contract, still supported on upgrades."""

from forge.generator import generate as _generate
from unittest.mock import patch


def generate(*args, **kwargs):
    with patch("forge.quality.formatting.canonicalize"):
        root = _generate(*args, **kwargs)
    (root / ".forge/quality.json").unlink(missing_ok=True)
    return root

"""Pytest fixtures for the platform-auth SDK test suite.

Fixtures defined in :mod:`platform_auth.testing` are re-exported here so
pytest can discover them without each test module importing them
explicitly. This is the canonical pytest pattern for fixture sharing.
"""

from __future__ import annotations

from platform_auth.testing import auth_env, issuer_trust_map, test_keypair

__all__ = ["auth_env", "issuer_trust_map", "test_keypair"]

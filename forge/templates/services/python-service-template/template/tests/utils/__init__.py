"""Shared test utilities — see ``docs/testing-generated-backends.md``.

Contracts in this package are mirrored across the three backend
languages so a fragment author writing tests in any backend uses the
same vocabulary.
"""

from tests.utils.errors import assert_error_envelope
from tests.utils.tenant import (
    authenticated_headers,
    tenant_factory,
)

__all__ = [
    "assert_error_envelope",
    "authenticated_headers",
    "tenant_factory",
]

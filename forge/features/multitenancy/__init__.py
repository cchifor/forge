"""``database.multitenancy`` feature — tenant-isolation discriminator.

Registers the ``database.multitenancy`` discriminator (``none`` |
``shared_rls`` | ``schema_per_tenant`` | ``db_per_tenant``) and its
tenant-resolution sub-options, plus the ``multitenancy_rls_python``
fragment that realises the ``shared_rls`` strategy on Python backends.

See ``options.py`` for the user-facing surface and ``fragments.py`` for
the realised implementation.
"""

from __future__ import annotations

from forge.api import ForgeAPI


def register(api: ForgeAPI) -> None:
    from forge.features.multitenancy import fragments, options

    options.register_all(api)
    fragments.register_all(api)

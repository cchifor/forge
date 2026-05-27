"""Retrieval-augmented generation stack with pluggable vector backends."""
from __future__ import annotations
from forge.api import ForgeAPI

def register(api: ForgeAPI) -> None:
    from forge.features.rag import options, fragments
    options.register_all(api)
    fragments.register_all(api)

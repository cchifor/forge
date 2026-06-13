"""Reference forge plugin — adds a **Vite (vanilla TypeScript)** frontend.

The frontend-surface companion to ``forge-go-backend``: it exercises
:meth:`forge.api.ForgeAPI.add_frontend`, registering a brand-new frontend
*framework* (``vite``) so ``forge --frontend vite`` generates a real, buildable
SPA without forking forge.

Why a vanilla Vite + TS SPA? It's the smallest genuinely-buildable frontend
that isn't one of the three built-ins (Vue/Svelte/Flutter): `npm ci && npm run
build` produces a `dist/` with no framework runtime to mock, giving the
plugin-frontend e2e a crisp "does it build" signal. A plugin frontend is a
Copier-only render (no forge-specific auth/api hooks), so the template just
needs to render and build.

The template ships **inside this package** and is handed to forge as an
absolute ``template_dir`` (built-in templates use relative paths; a plugin
can't assume its install location, so it resolves from ``__file__``).
``forge.generator`` joins template dirs with its templates root via
``pathlib``, so an absolute path renders correctly.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import FrontendSpec

_PACKAGE_ROOT = Path(__file__).resolve().parent
_TEMPLATE_DIR = _PACKAGE_ROOT / "vite-frontend-template"


def register(api: ForgeAPI) -> None:
    api.add_frontend(
        "vite",
        FrontendSpec(
            template_dir=str(_TEMPLATE_DIR),
            display_label="Vite (vanilla TS)",
            uses_subdirectory=True,
            version="1.0.0",
            node_based=True,
            build_dir="dist",
            package_manager="npm",
        ),
    )

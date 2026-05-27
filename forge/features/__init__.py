"""Built-in forge feature modules.

Each subpackage colocates one feature's option(s), fragment(s), and
template tree under a single root, mirroring the layout that
third-party plugins use under the ``forge.plugins`` entry-point group.

Registration is handled by ``forge.feature_loader.load_all()``, which
discovers each feature's ``feature.toml`` manifest, resolves
dependencies, and calls each feature's ``register(api)`` function in
topological order. This package is no longer eagerly imported.
"""

from __future__ import annotations

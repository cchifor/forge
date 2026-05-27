"""forge: Full-stack project generator."""

__version__ = "1.2.0a1"

# Import registries so they're available when needed. Feature and
# plugin registration is handled lazily by ``feature_loader.load_all()``
# (called from ``forge.cli.main`` before arg parsing).
from forge import fragments as _fragments  # noqa: F401, E402
from forge import options as _options  # noqa: F401, E402

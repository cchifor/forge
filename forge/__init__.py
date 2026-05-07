"""forge: Full-stack project generator."""

__version__ = "1.0.0"

# Eagerly import built-in feature subpackages so OPTION_REGISTRY and
# FRAGMENT_REGISTRY are fully populated by the time any caller reaches
# them. Order matters: ``forge.options`` and ``forge.fragments`` must
# import first, since each feature module calls ``register_option`` /
# ``register_fragment`` from the ``_registry`` submodules at import
# time. Features migrated under ``forge.features`` are equivalent to
# the namespace modules under ``forge.options.*`` / ``forge.fragments.*``
# but colocate options + fragments + templates per feature.
from forge import options as _options  # noqa: F401, E402
from forge import fragments as _fragments  # noqa: F401, E402
from forge import features as _features  # noqa: F401, E402

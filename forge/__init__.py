"""forge: Full-stack project generator."""

__version__ = "1.2.0a1"

# Importing these populates the option/fragment registry singletons (and,
# transitively via feature_loader, makes them available before any feature
# registers into them).
from forge import feature_loader as _feature_loader  # noqa: E402
from forge import fragments as _fragments  # noqa: F401, E402
from forge import options as _options  # noqa: F401, E402

# Register built-in features at import so any programmatic consumer
# (tests/matrix/runner.py, library users importing forge.generator /
# forge.cli.builder directly) sees populated registries without going
# through cli.main(). Loads ONLY built-ins — external plugins + the registry
# freeze stay in feature_loader.load_all() (called by cli.main() + conftest).
_feature_loader.load_builtin_features()

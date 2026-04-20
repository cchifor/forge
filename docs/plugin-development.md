# forge plugin development

This guide walks through building a forge plugin — a pip-installable package that extends forge with new options, fragments, backends, frontends, commands, or emitters.

## Trust model

**A forge plugin is a pip package.** Installing one grants it full Python execution rights when `forge` starts — forge does not sandbox plugin code. Treat plugin installation with the same care as any pip dependency:

- Pin plugins to specific versions in your requirements.
- Audit the source of third-party plugins before installing.
- Prefer plugins from trusted publishers.

Forge enforces the following at load time:

1. **Register-only on import.** Plugins declare themselves via a `register(api)` callable. Code in the plugin's module body runs at import but should not mutate forge state — only `register` should. Plugins that register fragments or options at import time (i.e. before `register` is called) will clash with forge's internal registries.
2. **Namespaced paths.** Option paths and fragment names must use a prefix that doesn't collide with built-ins (e.g. `mycompany.audit_log`, not `audit_log`). Forge raises on collision.
3. **No file I/O during load.** Plugins must not read, write, or execute files during discovery. Fragment application (which does touch the filesystem) happens inside forge's trust boundary, not the plugin's.

## Minimal plugin

### 1. Project structure

```
forge-plugin-example/
├── pyproject.toml
├── src/
│   └── forge_plugin_example/
│       ├── __init__.py
│       └── fragments/
│           └── hello_banner/
│               ├── python/
│               │   ├── inject.yaml
│               │   └── files/
│               │       └── hello.py
│               └── __init__.py
└── tests/
    └── test_register.py
```

### 2. `pyproject.toml`

```toml
[project]
name = "forge-plugin-example"
version = "0.1.0"
description = "Reference forge plugin that adds a `example.hello_banner` option"
requires-python = ">=3.11"
dependencies = ["forge>=1.0.0a1"]

[project.entry-points."forge.plugins"]
example = "forge_plugin_example:register"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

### 3. `src/forge_plugin_example/__init__.py`

```python
"""Reference forge plugin. Adds a single option that enables a banner fragment."""

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments import Fragment, FragmentImplSpec
from forge.options import FeatureCategory, Option, OptionType


def register(api: ForgeAPI) -> None:
    # 1. Declare the option the user will set.
    api.add_option(
        Option(
            path="example.hello_banner",
            type=OptionType.BOOL,
            category=FeatureCategory.PLATFORM,
            default=False,
            summary="Print a hello banner at startup (reference plugin)",
            description=(
                "When enabled, the generated Python backend prints "
                "'hello from forge-plugin-example' to stderr on every request. "
                "Demonstrates option → fragment wiring for plugin authors."
            ),
            enables={True: ("example_hello_banner",)},
        )
    )

    # 2. Declare the fragment the option enables.
    api.add_fragment(
        Fragment(
            name="example_hello_banner",
            category=FeatureCategory.PLATFORM,
            summary="Print a hello banner at startup",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir="forge_plugin_example/fragments/hello_banner/python",
                    dependencies=(),
                    env_vars=(),
                ),
            },
            capabilities=frozenset(),
        )
    )
```

### 4. Fragment contents

`src/forge_plugin_example/fragments/hello_banner/python/files/hello.py`:

```python
"""Printed at backend startup by the hello_banner fragment."""

import sys


def print_banner() -> None:
    print("hello from forge-plugin-example", file=sys.stderr, flush=True)
```

`src/forge_plugin_example/fragments/hello_banner/python/inject.yaml`:

```yaml
- target: src/app/main.py
  marker: FORGE:STARTUP_HOOKS
  snippet: |
    from .hello import print_banner
    print_banner()
```

### 5. Install and verify

```bash
pip install -e ./forge-plugin-example
forge plugins list
# Loaded plugins (1):
#   * example v0.1.0  (forge_plugin_example:register)
#       adds: 1 option(s), 1 fragment(s)
```

Generate a project with the option enabled:

```bash
forge --yes --no-docker --backend-language python \
      --set example.hello_banner=true \
      --output-dir /tmp --project-name banner-demo
```

## Plugin API reference

### `api.add_option(Option)`

Registers a new `Option` in the global `OPTION_REGISTRY`. The `path` must use a plugin-namespaced prefix. Forge raises `ValueError` on collision.

### `api.add_fragment(Fragment)`

Registers a new `Fragment` in the global `FRAGMENT_REGISTRY`. Each implementation's `fragment_dir` is resolved relative to `forge/templates/` — plugins can ship their own fragment directories by making their package install under `forge/templates/` or (cleaner) by providing an absolute path resolver.

For 1.0.0a1, plugins use the legacy relative-path convention. The 1.0.0a3 plugin SDK upgrade lands a path resolver that lets plugins ship fragments from their own package tree.

### `api.add_backend(language_value, spec)`

Registers a new `BackendLanguage` member plus its `BackendSpec`. **Phase 0.3 ships this as a stub** — plugin-defined backend languages require `BackendLanguage` to be a plugin-extensible enum, which is a 1.0.0a2 deliverable. Until then, calling `add_backend` with an unknown language raises `NotImplementedError`.

### `api.add_command(name, handler)`

Registers a new CLI subcommand. The handler signature is `(args: argparse.Namespace) -> int`. **Phase 0.3 ships this as a capture-only hook** — the dispatcher integration lands with the Phase 2 command-object polish (1.0.0a3).

### `api.add_emitter(target, emitter)`

Registers a code emitter for a target language or protocol. Targets are free-form strings — standard ones are `python`, `typescript`, `dart`, `openapi`. **Phase 0.3 ships this as a capture-only hook** — the emitter pipeline lands with Phase 1.3 (TypeSpec domain DSL; 1.0.0a2).

## Testing your plugin

A reference test using forge's test helpers:

```python
import pytest

from forge import plugins
from forge.api import ForgeAPI, PluginRegistration

@pytest.fixture(autouse=True)
def _reset():
    plugins.reset_for_tests()
    yield
    plugins.reset_for_tests()


def test_register_adds_option():
    from forge_plugin_example import register
    reg = PluginRegistration(name="example", module="forge_plugin_example")
    api = ForgeAPI(reg)
    register(api)
    assert reg.options_added == 1
    assert reg.fragments_added == 1
```

## Common pitfalls

1. **Import-time state mutation.** A plugin module that calls `register_fragment(...)` at import leaves the registries polluted even if the plugin's `register` function is never called. Keep plugin module bodies strictly declarative.
2. **Collision with built-ins.** Always prefix option paths and fragment names with your plugin identity: `mycompany.X`, `mycompany_X`.
3. **Assuming a specific forge version.** Use `dependencies = ["forge>=1.0.0a1,<2"]` and check the installed `forge.api.__version__` if your plugin needs version-specific behavior.
4. **Shipping fragments that target a backend the plugin doesn't declare support for.** `Fragment.implementations` must have an entry for every backend the fragment should apply to; omitting one silently skips that backend.

## Future plugin capabilities

The plugin SDK grows with each alpha:

| Alpha | Added capability |
|---|---|
| 1.0.0a1 (this release) | Options, fragments, hooks for commands/emitters |
| 1.0.0a2 | Plugin-defined backend languages; emitter pipeline wiring (Phase 1.3) |
| 1.0.0a3 | Command dispatcher integration (Phase 2.2); path resolver for plugin-owned fragment directories |
| 1.0.0a4 | Plugin-defined frontends with canvas package integration (Phase 3.1) |

See the 1.0 roadmap in `docs/roadmap.md` for scope and status.

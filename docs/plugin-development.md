# forge plugin development

This guide walks through building a forge plugin — a pip-installable package that extends forge with new options, fragments, backends, frontends, commands, or emitters.

## Quickstart (10 minutes)

The fastest path from zero to a working plugin. Copy the reference plugin, change the names, install in dev-mode, verify with `forge --plugins list`.

```bash
# 1. Clone or copy the reference plugin from the forge repo.
cp -r examples/forge-plugin-example my-plugin
cd my-plugin

# 2. Rename: src/forge_plugin_example/ → src/forge_plugin_<your-name>/
#    Update pyproject.toml's `name`, `[project.entry-points]`, and the
#    package directory under `src/`.

# 3. Edit src/forge_plugin_<name>/__init__.py:
#    - Replace `example.hello_banner` with your namespaced option path
#      (e.g. `mycompany.audit_log`).
#    - Replace `example_hello_banner` with your fragment name.
#    - Move/rename fragments/hello_banner/ to fragments/<your-fragment>/.

# 4. Install in dev-mode and verify the plugin loads.
uv pip install -e .
forge --plugins list
# Expected: your plugin appears under "Loaded plugins".

# 5. Generate a project with your option enabled.
forge --project-name demo --backend-language python \
      --features items --set <your-option-path>=true --quiet
# Inspect the generated project — your fragment's files + injections
# should be present.
```

**Common gotchas the [P0.2 CI gate](../tests/test_plugin_e2e.py) catches in the reference plugin (and that you'll hit in your own):**

1. **`Fragment(category=..., summary=...)` no longer exists.** User-visible metadata lives on the `Option`. The `Fragment` is implementation-only; constructor takes `name`, `implementations`, `depends_on`, `conflicts_with`, `capabilities`.
2. **`fragment_dir` must be an absolute path.** Plugins ship fragment templates inside their own package; pass `str(Path(__file__).resolve().parent / "fragments" / "<name>" / "<lang>")`. Built-in forge features now use the same convention (see `forge/features/<ns>/fragments.py` for live examples), so the resolver path is identical for built-ins and plugins.
3. **`files/` mirrors the backend root.** `files/src/app/hello.py` lands at `<backend>/src/app/hello.py` and is importable as `app.hello`. `files/hello.py` lands at `<backend>/hello.py` — outside the package, not importable.
4. **`compose.yaml` (P1.3) lives at the fragment root**, peer of the per-language sub-dirs, not inside `<lang>/`. The schema is documented in `forge/services/fragment_compose.py`'s module docstring.
5. **`pyproject.toml` needs `[tool.setuptools.package-data]`** so wheel installs ship your fragment tree (YAML + Python files). Editable installs (`pip install -e`) work without it; published wheels don't.

When stuck, run `forge --doctor` — it lists which plugins loaded, which failed, and (P1.4) whether `ts-morph` AST injection is reachable.

## Trust model

## Trust model

**A forge plugin is a pip package.** Installing one grants it full Python execution rights when `forge` starts — forge does not sandbox plugin code. Treat plugin installation with the same care as any pip dependency:

- Pin plugins to specific versions in your requirements.
- Audit the source of third-party plugins before installing.
- Prefer plugins from trusted publishers.

Forge enforces the following at load time:

1. **Register-only on import.** Plugins declare themselves via a `register(api)` callable. Code in the plugin's module body runs at import but should not mutate forge state — only `register` should. Plugins that register fragments or options at import time (i.e. before `register` is called) will clash with forge's internal registries.
2. **Namespaced paths.** Option paths and fragment names must use a prefix that doesn't collide with built-ins (e.g. `mycompany.audit_log`, not `audit_log`). Forge raises on collision.
3. **No file I/O during load.** Plugins must not read, write, or execute files during discovery. Fragment application (which does touch the filesystem) happens inside forge's trust boundary, not the plugin's.

## Stable API surface

The plugin contract — every name plugin authors target — is documented in `forge/api.py`'s module docstring with a per-symbol "Since" / "Compatibility" table. Stable symbols follow SemVer relative to the public ``forge`` package: a breaking signature change requires a major version bump.

P0.2 (1.1.0-alpha.2) added an end-to-end CI gate at [`.github/workflows/plugin-e2e.yml`](../.github/workflows/plugin-e2e.yml) that pip-installs `examples/forge-plugin-example/` against the working tree on every PR touching `forge/api.py`, `forge/plugins.py`, the option/fragment registries, or the example itself. The gate runs `pytest -m plugin_e2e` (defined in [`tests/test_plugin_e2e.py`](../tests/test_plugin_e2e.py)) which exercises the full discovery → registration → CLI → generation → update flow. Drift between the public API surface and the reference plugin surfaces here before release.

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
│               └── python/
│                   ├── inject.yaml
│                   └── files/
│                       └── src/
│                           └── app/
│                               └── hello.py
└── tests/
    └── test_register.py
```

The fragment's `files/` tree mirrors the *backend root* layout — a file at `files/src/app/hello.py` lands at `<backend>/src/app/hello.py` and is therefore importable as `app.hello`. Fragment directories must be passed to `FragmentImplSpec(fragment_dir=...)` as **absolute paths** (typically `str(Path(__file__).resolve().parent / "fragments" / "<name>" / "<lang>")`). Built-in forge features use the same pattern — `forge/features/<ns>/fragments.py` is a working reference, e.g. `forge/features/middleware/fragments.py` for the simplest case (`correlation_id`, single Python implementation, no inject.yaml).

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
    _FRAGMENT_ROOT = Path(__file__).resolve().parent / "fragments"
    api.add_fragment(
        Fragment(
            name="example_hello_banner",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=str(_FRAGMENT_ROOT / "hello_banner" / "python"),
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

Registers a new `Fragment` in the global `FRAGMENT_REGISTRY`. Each implementation's `fragment_dir` should be an absolute filesystem path — typically `str(Path(__file__).resolve().parent / "fragments" / "<name>" / "<lang>")`. The injector's `_resolve_fragment_dir` returns absolute paths verbatim, so plugin fragments and built-in forge fragments flow through identical resolution code.

Built-in forge features (under `forge/features/<ns>/`) follow the same convention — they're a useful reference when authoring a plugin. See `forge/features/middleware/fragments.py` (small, no inject.yaml) or `forge/features/rag/fragments.py` (larger, with cross-feature `depends_on`).

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

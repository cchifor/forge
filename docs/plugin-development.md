# forge plugin development

This guide walks through building a forge plugin — a pip-installable package that extends forge with new options, fragments, backends, frontends, commands, or emitters.

> **Compatibility note (1.2.0-alpha.1).** The public plugin SDK contract
> — `register_option`, `register_fragment`, `Option`, `Fragment`,
> `FragmentImplSpec`, the `forge.plugins` entry-point group — is
> unchanged. The 1.2 cutover that drops `src/service/` from the Python
> service template and routes consumer-side code through `weld.*`
> affects template internals only. Plugins that registered options or
> fragments under 1.0 / 1.1 keep working without edits. If your plugin
> generates Python source that imports from `service.*`, you'll want to
> point at the matching `weld.*` symbols (see the import table in
> `UPGRADING.md`) before users with `sdk_consumption=monorepo` regenerate.

## Quickstart (10 minutes)

The fastest path from zero to a working plugin. Copy the reference plugin, change the names, install in dev-mode, verify with `forge --plugins list`.

> **Faster path for the fragment itself.** If you only need to scaffold a single fragment's directory layout (manifest + per-backend `files/` + `fragments.py` registration stub), use `forge --plugins scaffold-fragment --name <name>` — it writes the same tree this Quickstart edits by hand, with `TODO` markers in each slot you have to fill in. See the [scaffold-fragment](#scaffold-fragment) section below for the full flag list.

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

## scaffold-fragment

`forge --plugins scaffold-fragment` writes a skeleton fragment tree — the same shape that lives at `examples/forge-plugin-example/src/forge_plugin_example/fragments/hello_banner/`, but parametrised on a name + backend set you pick. Use it when you've already got a plugin package (`pyproject.toml` + `register(api)` entry point) and want to add a new fragment without copy-pasting and renaming by hand.

```bash
# Default: writes ./plugins/forge-plugin-my_fragment/forge_plugin_my_fragment/fragments/my_fragment/
forge --plugins scaffold-fragment --name my_fragment

# Pick an explicit output directory + a subset of backends.
forge --plugins scaffold-fragment \
      --name audit_log \
      --output-dir src/forge_plugin_acme/fragments/audit_log \
      --backends python,rust

# Re-running on a populated directory refuses to clobber. --force wipes
# the tree first so the render is deterministic.
forge --plugins scaffold-fragment --name audit_log --output-dir ./out --force
```

Flags:

| Flag | Default | Notes |
| ---- | ------- | ----- |
| `--name` | (required) | Fragment name. Must be a valid Python identifier — it's embedded in generated source (`register_<name>`) and used as a directory name. Hyphens, leading digits, and reserved words are rejected before any file is written. |
| `--output-dir` | `./plugins/forge-plugin-<name>/forge_plugin_<name>/fragments/<name>/` | Where to render. Reuses the generic `--output-dir` flag. |
| `--backends` | `python,node,rust` | Comma-separated. Order is preserved; duplicates are deduped; unknown backends are a hard error. |
| `--force` | off | Wipe the target directory first if it already contains files. Without this, scaffold-fragment exits non-zero on a non-empty target. |

The rendered tree:

```
<output-dir>/
├── fragments.py           # registers Fragment via ForgeAPI.add_fragment
├── README.md              # next-steps cheat sheet
├── inject.yaml            # placeholder; delete once per-backend manifests exist
├── python/
│   ├── inject.yaml        # TODO stub — empty list
│   └── files/__init__.py  # TODO stub — copied verbatim into the backend
├── node/                  # only if 'node' in --backends
│   ├── inject.yaml
│   └── files/__init__.ts
└── rust/                  # only if 'rust' in --backends
    ├── inject.yaml
    └── files/lib.rs
```

Every file ships with a visible `TODO:` marker pointing at the slot the author has to fill in. The generated `fragments.py` is import-clean and `ast.parse`-clean out of the box — `from .fragments import register_<name>` works immediately; you just have to wire it into the plugin's top-level `register(api)` and pair it with an `Option`.

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

Registers a new `Option` in the global `OPTION_REGISTRY`. The `path` must use a plugin-namespaced prefix. Forge raises `PluginError` (code `PLUGIN_COLLISION`) on path-vs-path, path-vs-alias, alias-vs-path, or alias-vs-alias collisions.

Initiative #2 sub-task 1 routes this call through the same `forge.options.register_option` function the built-in features use, so plugin-declared `aliases=(...,)` populate `OPTION_ALIAS_INDEX` and behave identically to built-in aliases.

### `api.add_fragment(Fragment)`

Registers a new `Fragment` in the global `FRAGMENT_REGISTRY`. Each implementation's `fragment_dir` should be an absolute filesystem path — typically `str(Path(__file__).resolve().parent / "fragments" / "<name>" / "<lang>")`. The injector's `_resolve_fragment_dir` returns absolute paths verbatim, so plugin fragments and built-in forge fragments flow through identical resolution code.

Built-in forge features (under `forge/features/<ns>/`) follow the same convention — they're a useful reference when authoring a plugin. See `forge/features/middleware/fragments.py` (small, no inject.yaml) or `forge/features/rag/fragments.py` (larger, with cross-feature `depends_on`).

### `api.add_backend(language_value, spec)`

Registers a new `BackendLanguage` member plus its `BackendSpec`. **Phase 0.3 ships this as a stub** — plugin-defined backend languages require `BackendLanguage` to be a plugin-extensible enum, which is a 1.0.0a2 deliverable. Until then, calling `add_backend` with an unknown language raises `NotImplementedError`.

### `api.add_command(name, handler)`

Registers a new CLI subcommand. The handler signature is `(args: argparse.Namespace) -> int`. **Phase 0.3 ships this as a capture-only hook** — the dispatcher integration lands with the Phase 2 command-object polish (1.0.0a3).

### `api.add_emitter(target, emitter)`

Registers a code emitter for a target language or protocol. Targets are free-form strings — standard ones are `python`, `typescript`, `dart`, `openapi`. The emitter callable's signature is `(project_root: Path, config: ProjectConfig, resolved: ResolvedPlan | None) -> None`; `resolved` is the capability-resolver output and may be `None` on hosts that have not yet plumbed it (plugins MUST tolerate `None`).

Initiative #2 sub-task 2 wired this end-to-end: `forge.codegen.pipeline.run_codegen` walks `LOADED_PLUGINS` after the built-in passes and invokes each plugin's emitter. Last-loaded wins on target collision (a structured `plugin.emitter.target_collision` warning names both plugins); an emitter that raises is logged via `plugin.emitter.failed` and does not abort sibling emitters.

### `api.add_injector(suffix, injector)`

Registers a per-suffix injector with the pluggable `ApplierRegistry` (Pillar A.1, SDK 1.2). Before this hook the suffix dispatch in `forge/appliers/injection.py:_dispatch_injector` was a hardcoded `if/elif` chain — adding a new file type meant forking forge. Plugins now ship a `.go` / `.kt` / `.rs` injector at load time and the applier picks it up via `lookup_injector(target)`. `suffix` is a lowercase file extension including the leading dot (or the wildcard `"*"` to override the catch-all sentinel-based text fallback); `injector` is any callable matching `(file: Path, feature_key: str, marker: str, snippet: str, position: str) -> None` — the same signature every built-in injector (`inject_python` / `inject_ts` / `_inject_snippet`) exposes. Last-write wins on collision so plugins can layer wrapped versions of built-ins.

```python
from pathlib import Path

from forge.api import ForgeAPI


def inject_go(file: Path, feature_key: str, marker: str, snippet: str, position: str) -> None:
    text = file.read_text(encoding="utf-8")
    # Plugin-specific Go AST surgery here; mutate `text` in place and
    # honour the BEGIN/END sentinel idempotency contract.
    file.write_text(text, encoding="utf-8")


def register(api: ForgeAPI) -> None:
    api.require_sdk(">=1.2")
    api.add_injector(".go", inject_go)
```

### `api.add_hook(hook)` — telemetry / SBOM / supply-chain observers (SDK 1.2)

Registers a `forge.hooks.PhaseHook` that observes every generator phase. Callbacks fire from the existing `phase_timer` contexts that already wrap every phase, so plugins get full visibility without forking `forge.generator`. The three callbacks are `on_phase_start(name, ctx)`, `on_phase_end(name, ctx, duration_ms, error)`, and `on_generate_complete(report)` — the last one fires exactly once at the end of `generate()` with the populated `GenerationReport` (or `None` when the caller didn't request one).

A minimal telemetry hook that prints phase timings to stderr:

```python
from forge.api import ForgeAPI

class TelemetryHook:
    def on_phase_start(self, name, ctx): pass
    def on_phase_end(self, name, ctx, duration_ms, error):
        status = "FAIL" if error else "ok"
        print(f"[{status}] {name} {duration_ms}ms", file=__import__("sys").stderr)
    def on_generate_complete(self, report): pass

def register(api: ForgeAPI) -> None:
    api.require_sdk(">=1.2")
    api.add_hook(TelemetryHook())
```

Hook exceptions are swallowed and logged at WARNING by the dispatcher — a buggy hook will not crash generation, will not block sibling hooks, and the original exception (when a timed block itself raised) still re-raises normally. Hooks fire in registration order across all plugins (FIFO). The `ctx` dict is the kwargs the generator passed to `phase_timer(...)`; treat it as read-only — the dispatcher hands the same instance to every subsequent hook and the subsequent log emission.

Common use cases beyond telemetry: SBOM emitters that walk `report.file_inventory` at `on_generate_complete`, supply-chain signers that hash + sign the project tree, post-`forge new` shell scripts that fire automation against the generated repo.

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

## Featured Plugin tier

Pillar D.4 of the [forge improvement plan](#) introduces a curated tier
of community plugins that forge maintainers run e2e against `main`
nightly. Listing in the Featured tier signals that a plugin is held to
the same compatibility bar as `examples/forge-plugin-example` — a
forge change that breaks a Featured plugin breaks a forge CI job, not
just a downstream repo two weeks later.

### Criteria

A plugin qualifies for the Featured tier when it meets all of the
following:

1. **SDK contract:** the plugin's `register(api)` calls
   `api.require_sdk(">=1.2")` (or a later version). This guarantees
   the plugin is using the post-Pillar-A hook surface (`add_hook`,
   `add_injector`) rather than reaching into private forge internals.
2. **Integration tests in-repo:** the plugin's own repository ships
   integration tests covering at least one tier-1 fragment from
   `docs/matrix-status.md` — typically the fragment the plugin
   contributes or a built-in fragment it extends. Markers, runner, and
   command are the plugin author's choice; the point is that the
   plugin tests *something real* rather than a unit-level stub.
3. **PyPI publication:** the plugin ships as
   `forge-plugin-<name>` under the `forge-plugin-*` namespace on PyPI.
   Pre-release versions are fine (`forge-plugin-foo==0.1.0a1`) — the
   namespace is what counts. Plugins distributed only as git URLs are
   out of scope for the tier.
4. **Maintainer opt-in:** the plugin maintainer agrees, in writing on
   a GitHub Discussions thread, to forge maintainers running the
   plugin's e2e against latest forge nightly via
   `.github/workflows/featured-plugins-e2e.yml`. If the plugin's tests
   start failing, forge maintainers will open an issue against the
   plugin repo and (politely) hold the listing.
5. **Mutual badging:** the plugin's README carries a
   "Featured forge plugin" badge linking back to this section, and
   forge's `docs/plugin-development.md` plus `docs/known-issues.md`
   carry a row pointing at the plugin's repo + PyPI page. The badge is
   the public signal that the plugin author has signed up to the
   compatibility contract above.

### How the nightly job works

`.github/workflows/featured-plugins-e2e.yml` runs on a `schedule:`
(04:00 UTC) plus `workflow_dispatch`. For every entry in its matrix it
checks out forge `main`, checks out the plugin at its latest tag,
installs both into a single `uv` venv, runs `forge --plugins list`,
and (if the matrix row declares a `smoke_option`) runs a `forge new`
smoke that enables the plugin's option on a Python backend. Each row
writes a one-line markdown summary into `$GITHUB_STEP_SUMMARY`.

The matrix is currently empty by design (one placeholder row with
`enabled: false`); the workflow lints, the trigger is wired, and the
nightly invocation is a green no-op until the first real plugin opts
in. See the workflow file's header comment for the matrix-row schema
real entries follow.

### Current featured plugins

_(none yet — applications open via [GitHub Discussions](https://github.com/cchifor/forge/discussions). Open a thread titled "Featured plugin application: forge-plugin-&lt;name&gt;" with a link to the plugin repo, the PyPI page, and a one-paragraph confirmation of the five criteria above.)_

## Future plugin capabilities

The plugin SDK grows with each alpha:

| Alpha | Added capability |
|---|---|
| 1.0.0a1 (this release) | Options, fragments, hooks for commands/emitters |
| 1.0.0a2 | Plugin-defined backend languages (initial); emitter pipeline wiring shipped in 1.2.0-draft (Initiative #2 — `add_emitter` retains the callable + `run_codegen` invokes registered plugin emitters with `(project_root, config, resolved)` after the built-in passes) |
| 1.0.0a3 | Command dispatcher integration (Phase 2.2); path resolver for plugin-owned fragment directories |
| 1.0.0a4 | Plugin-defined frontends with canvas package integration (Phase 3.1) |

See the 1.0 roadmap in `docs/roadmap.md` for scope and status.

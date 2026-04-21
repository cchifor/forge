# Adding a new backend language

Forge's backend dispatch is driven by `BACKEND_REGISTRY` in `forge/config.py`. Adding a new backend (Go, Kotlin, Elixir, …) is a three-step task:

## 1. Create the Copier template

Copy an existing template under `forge/templates/services/` as a starting point — `services/python-service-template/` is the most heavily annotated, but `node-service-template/` is closer in shape to a typical compiled-language layout.

The template **must** define these Copier variables (read by `forge.variable_mapper.backend_context`):

| Variable | Source on `BackendConfig` | Notes |
|----------|---------------------------|-------|
| `project_name` | `bc.name` | Used as the service slug everywhere. |
| `project_description` | `bc.description` | One-liner for `Cargo.toml` / `package.json` / `pyproject.toml`. |
| `server_port` | `bc.server_port` | Host port; Vite proxy and Docker map to this. |
| `db_name` | `bc.name.replace("-", "_")` | Postgres database name. |
| `entity_plural` | `bc.features[0]` | Drives the seed CRUD entity. |
| *your_version_field* | declared in the registry | E.g. `go_version`, `kotlin_version`. |

Place template files under `template/` (Copier convention). Use `{{project_name}}`, `{{server_port}}`, etc.

## 2. Write a `BackendToolchain`

Each backend carries a toolchain — an object that satisfies the
`forge.toolchains.BackendToolchain` Protocol and runs the language's
install / verify / post-generate steps. Built-ins live in
`forge/toolchains/{python,node,rust}.py`; add yours next to them:

```python
# forge/toolchains/go.py
from pathlib import Path

from forge.toolchains import Check
from forge.toolchains._runner import run_backend_cmd


class GoToolchain:
    name = "go"

    def install(self, backend_dir: Path, *, quiet: bool = False) -> None:
        # ``go mod tidy`` produces a ``go.sum`` the Docker image depends on,
        # so run it unconditionally (required=True surfaces a missing ``go``
        # binary as a hard error instead of a warn-and-continue).
        run_backend_cmd(
            backend_dir,
            ["go", "mod", "tidy"],
            "Tidy modules",
            quiet=quiet,
            required=True,
        )

    def verify(self, backend_dir: Path, *, quiet: bool = False) -> list[Check]:
        return [
            run_backend_cmd(backend_dir, ["go", "build", "./..."], "Build", quiet=quiet),
            run_backend_cmd(backend_dir, ["go", "vet", "./..."], "Vet", quiet=quiet),
            run_backend_cmd(backend_dir, ["go", "test", "./..."], "Tests", quiet=quiet),
        ]

    def post_generate(self, backend_dir: Path, *, quiet: bool = False) -> None:
        return None


GO_TOOLCHAIN = GoToolchain()
```

The three methods correspond to three generator phases:

- **`install`** runs whenever the generator is writing to disk (i.e.
  not `--dry-run`). Use for steps that produce artifacts the rest of
  the generation depends on (lockfiles for Docker, compile caches).
  Can be a no-op.
- **`verify`** runs in interactive mode (not `--quiet`, not
  `--dry-run`) and is the hook that `forge doctor` / the matrix
  runner invoke. Returns a list of `Check` — an empty list is the
  honest answer if there's nothing to verify.
- **`post_generate`** is an optional finalization hook (formatting
  passes, sidecar files); default to a no-op.

## 3. Extend `BackendLanguage` and `BACKEND_REGISTRY`

In `forge/config.py`:

```python
class BackendLanguage(Enum):
    PYTHON = "python"
    NODE = "node"
    RUST = "rust"
    GO = "go"  # <- add

@dataclass
class BackendConfig:
    ...
    go_version: str = "1.23"  # <- add the version field


def _go_toolchain_factory():
    from forge.toolchains.go import GO_TOOLCHAIN
    return GO_TOOLCHAIN


BACKEND_REGISTRY[BackendLanguage.GO] = BackendSpec(
    template_dir="services/go-service-template",
    display_label="Go (Echo)",
    version_field="go_version",
    version_choices=("1.23", "1.22", "1.21"),
    toolchain=_go_toolchain_factory(),
)
```

The generator dispatches `spec.toolchain.install(...)` and
`spec.toolchain.verify(...)` uniformly — no further edits to
`generator.py` are required. The old language-specific dispatch dict
was removed in Epic S; anything that used to live in
`_setup_<lang>_backend` now lives in `GoToolchain.install/verify`.

## 4. (Optional) docker-compose & init-db templates

Update `forge/templates/deploy/docker-compose.yml.j2` and `forge/templates/deploy/init-db.sh.j2` if your backend needs a non-standard service definition or a per-language Dockerfile.

## 5. Plugins (don't edit core registries)

Plugins register a new backend via `api.add_backend(language_value, BackendSpec(...))` — pass your toolchain in the spec. The generator treats plugin backends identically to built-ins: no generator-side changes are needed.

```python
# In your plugin's register(api) entry point:
from forge.config import BackendSpec
from my_plugin.toolchain import MyLangToolchain

api.add_backend(
    "mylang",
    BackendSpec(
        template_dir="/abs/path/to/mylang-template",  # or packaged-relative
        display_label="MyLang (Web)",
        version_field="mylang_version",
        version_choices=("1.0", "0.9"),
        toolchain=MyLangToolchain(),
    ),
)
```

## 6. Add an e2e case

Add a parametrized case in `tests/e2e/test_full_generation.py` that scaffolds your new backend and runs its native test suite. Use the `require_<tool>` fixtures from `tests/e2e/conftest.py` so contributors without the toolchain installed see clean skips.

## CLI flags (no work required)

The interactive prompt picks up the new language automatically via `BACKEND_REGISTRY`. Headless callers can already pass `--backend-language=go` because the CLI argparse `choices=` is generated from `BackendLanguage` values — extend that list if you used a constant instead of generating from the enum.

## Next step: opt-in features

A new backend also needs fragment implementations for any Tier 1 middleware and opt-in features your users will expect (correlation_id, rate limiting, observability, …). See [FEATURES.md](FEATURES.md) for the fragment format and how to register a `FragmentImplSpec` under an existing `FeatureSpec` for your language.

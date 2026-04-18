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

## 2. Extend `BackendLanguage` and `BACKEND_REGISTRY`

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

BACKEND_REGISTRY[BackendLanguage.GO] = BackendSpec(
    template_dir="services/go-service-template",
    display_label="Go (Echo)",
    version_field="go_version",
    version_choices=("1.23", "1.22", "1.21"),
)
```

That's it for the registry — `_prompt_backend`, `backend_context`, and `_generate_single_backend` all read from it.

## 3. Wire up `_setup_*_backend`

In `forge/generator.py`, add a setup function that runs after Copier renders the template (linting, tests, etc.):

```python
def _setup_go_backend(backend_dir: Path) -> None:
    _run_backend_cmd(backend_dir, ["go", "mod", "tidy"], "Tidy modules")
    _run_backend_cmd(backend_dir, ["go", "build", "./..."], "Build")
    _run_backend_cmd(backend_dir, ["go", "test", "./..."], "Tests")
```

Then add it to the `backend_setup` dict inside `generate()`:

```python
backend_setup: dict[BackendLanguage, Callable[[Path], None]] = {
    BackendLanguage.PYTHON: _setup_backend,
    BackendLanguage.NODE: _setup_node_backend,
    BackendLanguage.RUST: _setup_rust_backend,
    BackendLanguage.GO: _setup_go_backend,  # <- add
}
```

If your toolchain produces a lockfile that Docker builds depend on (the way `npm install` produces `package-lock.json`), add an unconditional `required=True` invocation in `generate()` immediately after `_generate_single_backend`.

## 4. (Optional) docker-compose & init-db templates

Update `forge/templates/deploy/docker-compose.yml.j2` and `forge/templates/deploy/init-db.sh.j2` if your backend needs a non-standard service definition or a per-language Dockerfile.

## 5. Add an e2e case

Add a parametrized case in `tests/e2e/test_full_generation.py` that scaffolds your new backend and runs its native test suite. Use the `require_<tool>` fixtures from `tests/e2e/conftest.py` so contributors without the toolchain installed see clean skips.

## CLI flags (no work required)

The interactive prompt picks up the new language automatically via `BACKEND_REGISTRY`. Headless callers can already pass `--backend-language=go` because the CLI argparse `choices=` is generated from `BackendLanguage` values — extend that list if you used a constant instead of generating from the enum.

## Next step: opt-in features

A new backend also needs fragment implementations for any Tier 1 middleware and opt-in features your users will expect (correlation_id, rate limiting, observability, …). See [FEATURES.md](FEATURES.md) for the fragment format and how to register a `FragmentImplSpec` under an existing `FeatureSpec` for your language.

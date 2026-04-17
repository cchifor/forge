# Contributing to forge

Thanks for your interest. Forge is a small CLI; the codebase is intentionally compact and the bar for changes is keeping it that way.

## Setup

```bash
git clone <repo>
cd forge
uv sync --all-extras --dev
uv run pre-commit install
```

## Workflow

```bash
make check       # ruff + ty + unit tests (fast, ~10s)
make lint        # ruff check
make typecheck   # ty check
make test        # pytest (excludes -m e2e)
make e2e         # full e2e suite (slow — needs uv, npm, cargo, git)
make format      # ruff format
```

CI runs `make check` on Linux + Windows for Python 3.11/3.12/3.13. The `e2e` workflow runs nightly and on PRs that touch templates or the generator.

## Adding a new feature

- **New backend language**: see [docs/adding-a-backend.md](docs/adding-a-backend.md). The `BACKEND_REGISTRY` is the single source of truth.
- **New CLI flag**: add to `_parse_args` in `forge/cli.py` and read via `_get(args, "flag", cfg, "block", "key", default=...)` in `_build_config`.
- **Template change**: bump nothing — versioning is by git commit (recorded in `forge.toml` of generated projects via the `_commit:` Copier directive). Add an e2e case if behaviour changes.
- **New error path**: raise `GeneratorError` from `forge.generator`; `cli.main()` already routes it to JSON envelope or stderr+exit(2).

## Code style

- Type hints required on all public functions and module-level callables; `ty check forge/` must pass.
- Lint rules: `ruff` with `select = E,F,I,UP,B,SIM`, line length 100, exclude `forge/templates/`.
- No new dependencies without a clear motivation; keep the install footprint small.
- Tests live in `tests/`; e2e cases live in `tests/e2e/` and are marked `@pytest.mark.e2e`.

## Commit & PR conventions

- Subject ≤ 50 chars, imperative mood (`add Go backend support`, `fix git init crash on Windows`).
- One logical change per PR; keep refactors and feature additions separate.
- PR description: motivation + a one-line "how to verify" (typically a `make` target or `uv run forge ...` command).
- The CHANGELOG is updated on release, not per-PR.

## Reporting issues

Include:
- `forge --help` output (confirms version)
- The exact `forge ...` command that triggered the issue
- For generation bugs: the contents of `forge.toml` from the generated project
- For template bugs: the rendered file's location relative to the project root

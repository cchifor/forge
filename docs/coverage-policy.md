# Coverage Policy

Forge uses two layers of coverage gates:

1. **Project-wide floor** — configured in `pyproject.toml` as `fail_under`.
   Catches outright regressions across the whole package.
2. **Per-module critical-path floors** — enforced by `tests/test_coverage_gates.py`.
   Applies to the modules where a silent coverage drop would bite generated
   projects on every `forge --update`: the resolver, the fragment applier,
   merge semantics, provenance, and the AST injectors.

Every PR runs the `coverage` job in `ci.yml` (ubuntu × Python 3.13 only) and
either passes both gates or blocks the merge.

## Why two layers?

The project-wide floor alone is too coarse — adding a large test-free module
can leave the overall percentage unchanged while the critical path decays
silently. The per-module gate makes every regression in the modules we care
about surface in a single line of the failing test output.

## Current floors (1.1.0-alpha.1)

Floors are measured - 2pp: a small, incidental coverage drop won't block
an unrelated PR, but a meaningful decline does. Targets are the steady
state we're ratcheting toward over the 1.x series. The *Measured* column
is the coverage at the point each floor was set — useful context when
deciding how much headroom a PR has.

| Module                           | Measured | Floor | Target  | Why it matters                                                      |
| -------------------------------- | -------- | ----- | ------- | ------------------------------------------------------------------- |
| `forge/capability_resolver.py`   | 97.0%    | 95%   | 98%     | Single choke-point: options → fragments → ordered plan              |
| `forge/feature_injector.py`      | 90.0%    | 88%   | 95%     | Applier orchestration; most complex module in the core              |
| `forge/merge.py`                 | 86.7%    | 85%   | 95%     | Three-way merge decision table; silent bugs here lose user edits    |
| `forge/provenance.py`            | 96.7%    | 95%   | 98%     | File classification drives `--update` safety                        |
| `forge/injectors/python_ast.py`  | 97.8%    | 95%   | 98%     | Fragment injection into Python templates via LibCST                 |
| `forge/injectors/ts_ast.py`      | 97.3%    | 95%   | 98%     | Fragment injection into TS/JS templates (regex + ts-morph sidecar)  |
| `forge/updater.py`               | 80.5%    | 78%   | 90%     | `forge --update` — re-apply + classification + re-stamp             |
| **Project-wide**                 | 83.5%    | 75%   | 85%     | Whole-package safety net; excludes `forge/templates/` by design     |

## Ratchet policy

- **Each sprint** that touches a critical-path module bumps its floor by at
  least 1 percentage point — the PR either improves coverage or explicitly
  accepts the new baseline.
- **Lowering a floor** requires:
  1. A CHANGELOG entry under *Changed* calling out the regression and the
     justification (e.g. "dropping a rarely-exercised branch after confirming
     it's unreachable").
  2. An RFC-002 amendment if the regression is >2pp or if it drops a floor
     below its initial value.
- **Adding a new critical-path module** to the gate table follows the same
  RFC-002 contract as option rename codemods — the PR that adds the module
  proposes its initial floor and target.

## How to add a module to the gate

1. Decide the initial floor: run `uv run pytest -m "not e2e" --cov` locally
   and round the measured percentage down to the nearest 5.
2. Decide the target: realistic steady state, usually 80–95% depending on
   how much of the module is pure-function logic vs. IO wrappers.
3. Add a row to the `MODULE_FLOORS` table in
   `tests/test_coverage_gates.py` with both values.
4. Update the table in this document with the same values.
5. Include the `coverage` CI job run in the PR description so reviewers see
   the new floor is green.

## How to lower a floor (if you must)

1. Identify the covered lines the PR removes or un-exercises. A `git diff`
   against the test file often shows the root cause.
2. Justify in CHANGELOG why the uncovered code is safe — ideally because it
   was unreachable, dead, or replaced by a higher-level test that exercises
   the same behaviour through a different entry point.
3. Lower the `MODULE_FLOORS` entry and this document's table in the same PR.
4. Re-affirm the target (it does not move when the floor moves; the delta
   goes on the "how much longer to steady state" debt line).

## What's NOT gated

- `forge/templates/` — these are generated-project files copied verbatim.
  They're shape-tested via `tests/test_golden_snapshots.py` and functionally
  tested via `tests/e2e/`. Line coverage is meaningless for Jinja templates.
- `forge/cli/` — CLI dispatch is exercised via integration tests that
  subprocess-invoke `forge`. Line coverage under-reports because each subcommand
  runs its dispatcher in a different process. Epic C's `VerbHandler` protocol
  will make this testable with plain pytest; the gate adds `forge/cli/` once
  that lands.
- `forge/templates/_fragments/*/python/files/**` — shipped *inside* generated
  projects and tested by their own pytest suite at e2e time, not forge's.

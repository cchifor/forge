# Mutation testing

`forge` uses [mutmut](https://github.com/boxed/mutmut) to hunt for tests that pass regardless of the implementation being correct. Mutation testing is slow by nature; we scope it to the fragment-injection critical path where silent regressions hurt most.

## Scoped modules

```
forge/appliers/injection.py                                — zone semantics, injection dispatch
forge/appliers/plan.py                                     — FragmentPlan + _Injection construction
forge/sync/merge.py                                        — three-way decision table
forge/sync/provenance.py                                   — SHA normalization + classification
forge/injectors/python_ast.py                              — LibCST-anchored Python injection
forge/injectors/ts_ast.py                                  — regex-anchored TypeScript injection
forge/sync/forge_to_project/updater/__init__.py            — forge --update orchestration
forge/sync/forge_to_project/updater/_merge_driver.py       — file-level three-way merge driver
forge/sync/forge_to_project/updater/_template_render.py    — base-template re-render path
```

These are the paths listed in `pyproject.toml` under `[tool.mutmut] paths_to_mutate`. The pre-Epic-A `forge/feature_injector.py`, `forge/merge.py`, `forge/provenance.py`, and `forge/updater.py` modules were decomposed into the layout above; `tests/test_mutmut_config.py` asserts the pyproject path list and `tests/mutmut_baselines.json` stay in sync with the live tree.

## Running

```bash
# Kick off a full run. Expect ~20-40 minutes on a modern laptop.
uvx mutmut run

# Browse surviving mutants.
uvx mutmut results

# Show the diff for a specific mutant.
uvx mutmut show <id>
```

## Expected baseline

Per-module floors live in `tests/mutmut_baselines.json` — that file is the source of truth, and `tests/test_mutmut_config.py` asserts every module in the pyproject path list has a matching budget there. Current floors:

| Module | Kill rate ≥ | Survivors ≤ |
|---|---|---|
| `forge/appliers/injection.py` | 0.95 | 5 |
| `forge/appliers/plan.py` | 0.95 | 5 |
| `forge/sync/merge.py` | 1.0 | 0 |
| `forge/sync/provenance.py` | 1.0 | 0 |
| `forge/injectors/python_ast.py` | 0.90 | 3 |
| `forge/injectors/ts_ast.py` | 0.90 | 3 |
| `forge/sync/forge_to_project/updater/__init__.py` | 0.85 | 3 |
| `forge/sync/forge_to_project/updater/_merge_driver.py` | 0.90 | 1 |
| `forge/sync/forge_to_project/updater/_template_render.py` | 0.90 | 1 |

The three updater files split the pre-Epic-A `forge/updater.py` budget (≤5 survivors) by line count so the aggregate cap is preserved; `test_mutmut_config.py::test_updater_aggregate_survivor_budget_matches_pre_decomposition_cap` enforces that invariant.

Numbers are aspirational targets — CI does not block on mutation score since runs are expensive and flaky under timing-sensitive tests. The gate is: **every breaking-change PR to these modules must run mutmut locally and include the kill delta in the PR body** (how many new mutants were killed vs. survived).

## Adding a target

When extending the critical path (e.g., adding a new zone to `_apply_zoned_injection`), add the module to the `paths_to_mutate` list. When adding a new injector (e.g., Rust syn-based), do the same.

## Known survivors

Any mutation that only affects logging messages, docstrings, or error text is expected to survive — our tests don't match on log / error *text*, only on *occurrence* and *exit code*. These are documented in [`tests/mutmut_known_survivors.md`](../tests/mutmut_known_survivors.md) when encountered so the reviewer doesn't re-investigate the same mutants across alphas.

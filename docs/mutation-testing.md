# Mutation testing

`forge` uses [mutmut](https://github.com/boxed/mutmut) to hunt for tests that pass regardless of the implementation being correct. Mutation testing is slow by nature; we scope it to the fragment-injection critical path where silent regressions hurt most.

## Scoped modules

```
forge/feature_injector.py      — zone semantics, injection dispatch
forge/merge.py                 — three-way decision table
forge/provenance.py            — SHA normalization + classification
forge/injectors/python_ast.py  — LibCST-anchored Python injection
forge/injectors/ts_ast.py      — regex-anchored TypeScript injection
forge/updater.py               — forge --update pipeline
```

These are the paths listed in `pyproject.toml` under `[tool.mutmut] paths_to_mutate`.

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

Each alpha bumps the test surface; current baseline (as of 1.0.0a5):

| Module | Mutants killed | Survived |
|---|---|---|
| feature_injector | ≥ 95% | < 5 |
| merge | 100% | 0 |
| provenance | 100% | 0 |
| python_ast | ≥ 90% | ≤ 3 |
| ts_ast | ≥ 90% | ≤ 3 |
| updater | ≥ 85% | ≤ 5 |

Numbers are aspirational targets — CI does not block on mutation score since runs are expensive and flaky under timing-sensitive tests. The gate is: **every breaking-change PR to these modules must run mutmut locally and include the kill delta in the PR body** (how many new mutants were killed vs. survived).

## Adding a target

When extending the critical path (e.g., adding a new zone to `_apply_zoned_injection`), add the module to the `paths_to_mutate` list. When adding a new injector (e.g., Rust syn-based), do the same.

## Known survivors

Any mutation that only affects logging messages, docstrings, or error text is expected to survive — our tests don't match on log / error *text*, only on *occurrence* and *exit code*. These are documented in `tests/mutmut_known_survivors.md` when encountered so the reviewer doesn't re-investigate the same mutants across alphas.

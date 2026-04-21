# ty canary fixtures

Twelve small Python files that exercise the five ty rules forge depends on
plus a handful of inference primitives. Each file starts with one of:

```
# expect: error[<rule-id>]
# expect: ok
```

`tests/test_ty_canary.py` runs `uv run ty check` against this directory and
asserts the set of reported diagnostics matches the annotations — one
diagnostic per `expect: error` file, no diagnostics on `expect: ok` files.

**Purpose.** Isolate upstream ty regressions from forge regressions. If the
forge typecheck job fails but the canary passes, the bug is in forge. If
the canary fails, ty's behaviour changed and the pinned version in
`pyproject.toml` needs to move (via `.github/workflows/ty-upgrade.yml`).

## Rule coverage

| File                               | Rule                         | Expect |
| ---------------------------------- | ---------------------------- | ------ |
| `rule_unresolved_import_err.py`    | `unresolved-import`          | error  |
| `rule_unresolved_import_ok.py`     | `unresolved-import`          | ok     |
| `rule_invalid_argument_type_err.py`| `invalid-argument-type`      | error  |
| `rule_invalid_argument_type_ok.py` | `invalid-argument-type`      | ok     |
| `rule_invalid_return_type_err.py`  | `invalid-return-type`        | error  |
| `rule_invalid_return_type_ok.py`   | `invalid-return-type`        | ok     |
| `rule_missing_argument_err.py`     | `missing-argument`           | error  |
| `rule_missing_argument_ok.py`      | `missing-argument`           | ok     |
| `rule_unknown_argument_err.py`     | `unknown-argument`           | error  |
| `rule_unknown_argument_ok.py`      | `unknown-argument`           | ok     |
| `inference_typed_dict_ok.py`       | TypedDict inference          | ok     |
| `inference_generic_protocol_ok.py` | Generic Protocol inference   | ok     |

Adding a new fixture: start from the closest existing file, update the
header to the right `# expect:` annotation, and add a row to both the
table above and the `MODULE_FLOORS`-style structure in
`tests/test_ty_canary.py`.

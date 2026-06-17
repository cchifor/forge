# Known mutation survivors

Structured log of mutmut survivors that are **expected** and need no further
investigation. Referenced by [`docs/mutation-testing.md`](../docs/mutation-testing.md#known-survivors).

A survivor is *expected* when the mutated code has no behavioural contract our
tests assert. The suite matches on **occurrence** and **exit code**, never on
log / error / docstring *text*, so a mutation that only rewrites such text
cannot be killed by design. Recording it here means a reviewer doesn't
re-triage the same mutant across alphas.

## How to use this file

When `uvx mutmut results` shows a survivor on a `paths_to_mutate` module:

1. `uvx mutmut show <id>` — inspect the diff.
2. If it only changes a log message, docstring, comment, or human-facing error
   string (no control-flow / return-value / exit-code effect), add a row below.
3. Otherwise it's a real test gap — write a test that kills it (do **not** list
   it here).

Keep `survivors_max` in [`tests/mutmut_baselines.json`](mutmut_baselines.json)
consistent with the count of accepted survivors per module.

## Accepted survivors

| Module | Mutant (kind) | Why it survives | Recorded |
| --- | --- | --- | --- |
| _none recorded yet_ | — | — | — |

> Add one row per accepted survivor, e.g.:
> `| forge/sync/merge.py | log f-string text | tests assert the log fires (caplog), not its wording | 1.3.0 |`

## Categories that are always accepted

- **Logging message text** — `logger.{debug,info,warning}("…")` wording. Tests
  use `caplog` to assert the record exists, not its message.
- **Docstrings / comments** — no runtime effect.
- **Human-facing error text** — the *message* string inside a raised exception.
  Tests assert the exception **type** and the process **exit code**, not the
  prose. (A mutation that changes the exception *type* or removes the `raise`
  is a real survivor — kill it.)

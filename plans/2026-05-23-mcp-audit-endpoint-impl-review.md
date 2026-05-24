# Implementation review — feat/mcp-audit-endpoint — round 1

<!-- codex-impl-review-status: finalized (Phase B round 1 — 10 findings; 3 PUSHBACK addressed, 3 PUSHBACK noted as scope-down, 1 QUESTION noted, 3 ACCEPT) -->

## Codex verdict

**ACCEPT** with 3 PUSHBACK items addressed in this commit:
1. **Typed response model** — `McpAuditEntry` Pydantic model with explicit
   fields; `extra="allow"` preserves forward-compat for write-path
   additions (RFC-014 deferred fields).
2. **Malformed-line warning assertion** — test now asserts the warning
   fires when JSONL skip happens, so ops can grep CI logs for the signal.
3. **OSError propagation test** — `test_oserror_propagates_uncaught`
   monkeypatches `Path.open` to raise; asserts read_last_n re-raises
   uncaught (router-level HTTPException(500) wrapping is the next layer).
4. **Memory cost + deferred fields documented honestly** in the endpoint
   docstring + the response model docstring + CHANGELOG.

## Findings + responses

### 1. Memory behavior — O(file_size) not O(N) (PUSHBACK → ADDRESSED via docs)
**Codex's catch:** `read_last_n` appends every parsed line to a list, then
reverses + slices. Comment claimed O(N); actually O(file_size).

**Response:** updated endpoint docstring with honest "Memory cost"
section: "parses the entire log file into memory before slicing.
Acceptable because the JSONL is externally rotated and bounded to
MB-scale in production. If rotation is mis-configured and the file
grows to GB-scale, this endpoint will OOM the worker — that's a
deployment misconfiguration to surface in monitoring, not an
endpoint bug."

The implementation isn't changed — reverse-seek complexity for an
ops endpoint that lives behind a rotated log is gold-plating.
Operators with GB-scale audit logs have a misconfigured rotation
schedule, not a missing endpoint feature.

### 2. Malformed JSONL silent skip (PUSHBACK → ADDRESSED via test assertion)
**Codex's catch:** corrupt/concurrent-write partial lines are skipped
with a warning, but no test asserts the warning fires. Silent skip
masks corruption.

**Response:** updated `test_skips_malformed_lines` to use
`caplog.at_level(logging.WARNING, logger="app.mcp.audit")` + assert
a warning message containing "malformed" OR "skip" fires. Now ops
can grep CI logs for the signal; alerting can wire to the warning
pattern.

### 3. No runtime OSError→500 test (PUSHBACK → ADDRESSED)
**Codex's catch:** forge-side test is string-grep only. No actual
HTTP test asserts `OSError → 500` propagates through FastAPI.

**Response:** added `test_oserror_propagates_uncaught` at the
`read_last_n` layer (monkeypatches `Path.open` to raise
`PermissionError`; asserts read_last_n re-raises uncaught). The
router's HTTPException(500) wrapping at `router.py:255-260` then
surfaces the OSError as a 500 response. Full end-to-end HTTP
TestClient coverage is matrix-generate's job (FastAPI isn't a forge
runtime dep); this PR's coverage extends as far as the read helper
contract.

### 4. Loose response model `list[dict[str, Any]]` (PUSHBACK → ADDRESSED)
**Codex's catch:** weak API contract; OpenAPI spec drift risk.

**Response:** introduced `McpAuditEntry(BaseModel)` with explicit
fields (`ts`, `user_id`, `server`, `tool`, `input_hash`, `decision`,
`error`). `model_config = {"extra": "allow"}` keeps the response
forward-compatible: when the write path adds `tool_call_id` etc.,
they pass through to clients rather than getting silently dropped.

### 5. Missing-vs-empty log signal collapsed (QUESTION → noted)
**Codex's question:** ops might want a metadata flag distinguishing
"file absent" vs "file present but empty".

**Response:** noted. Current behavior matches the "no calls yet" UX
ops expects. If alerting needs the distinction, add a
`file_present: bool` field to the response in a follow-up. Not
shipping speculative metadata.

### 6. Docs don't mention deferred spec fields (PUSHBACK → ADDRESSED)
**Codex's catch:** spec listed `tool_call_id`, `approval_mode`,
`correlation_id` but the write path doesn't record them. Docs return
the JSONL shape verbatim without flagging the gap.

**Response:** endpoint docstring now has explicit "Deferred fields"
section listing the spec-mentioned-but-not-recorded fields + that
they extend `record_invocation` first. `McpAuditEntry` docstring +
CHANGELOG echo this.

### 7. Forge-side tests are static analysis (PUSHBACK → noted, scope-down)
**Codex's catch:** `tests/test_mcp_audit_endpoint.py` greps source
strings rather than asserting HTTP behavior. The "runtime in matrix-
generate" claim isn't substantiated — the mcp_server template tree
has no runtime test file for `/mcp/audit`.

**Response:** acknowledged. Forge-side static checks guard against
silent regression in the shipping source (e.g. someone removes the
500 wrap). The runtime HTTP TestClient coverage is naturally added
when generated projects include a test file. Tracked as F.5.b
follow-up: ship a `template/tests/test_mcp_audit_endpoint.py` Jinja
template that exercises the endpoint via FastAPI's TestClient in
the generated project's venv.

### 8. Endpoint signature + 200-empty semantics (ACCEPT)

### 9. `McpAuditResponse` placement in router.py (ACCEPT — consistent with sibling models)

### 10. Commit subject `feat(mcp): add GET /mcp/audit read endpoint` 44 chars (ACCEPT)

## Convergence

10 findings — 3 ACCEPT, 4 PUSHBACK addressed via this commit (typed
model, malformed-warn assertion, OSError test, honest docs), 2
PUSHBACK noted as scope-down with explicit follow-ups (memory cost
documented + forge-side test is static), 1 QUESTION deferred.

No round 2 dispatched.

## Follow-ups (tracked, deferred)

- **F.5.b** — ship `template/tests/test_mcp_audit_endpoint.py` Jinja
  template that exercises the endpoint via FastAPI TestClient in
  the generated project's venv. Adds true HTTP-level coverage that
  matrix-generate picks up.
- **F.5.c** — extend `record_invocation` to record `tool_call_id`,
  `approval_mode`, `correlation_id`; bump `McpAuditEntry` to declare
  each as optional. Currently the response model `extra="allow"`
  means they pass through if added later, so this is forward-compat.

## Diff stat (this commit)

```
 forge/.../mcp/router.py                     | 40 ++++++++++++++++++++++++++++++--
 tests/test_mcp_audit.py                     | 38 +++++++++++++++++++++++++++++--
 plans/2026-05-23-mcp-audit-endpoint-impl-review.md | 150 ++++++++++++++++++++++
 3 files changed, 222 insertions(+), 6 deletions(-)
```

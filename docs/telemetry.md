# Forge Telemetry

Opt-in usage statistics for forge's harvest / verify / update / accept-harvested /
reapply-baseline / emit-pr / resolve verbs. **Off by default.** When opted in,
forge emits structured events to a local JSONL file and (optionally) to a remote
HTTPS endpoint of the operator's choice.

This document is the **privacy contract** — the data shapes listed here are the
shapes forge actually emits. The minimal-field scope's allowlist is enforced at
the module level (`forge.telemetry._MINIMAL_ALLOWED_FIELDS`), so if a future
event adds a field, both this doc and that allowlist must be updated.

## 1. What telemetry collects

Every event carries the same envelope:

| Field            | Type    | Description                                            |
|------------------|---------|--------------------------------------------------------|
| `event`          | string  | Stable event name (see vocabulary below).              |
| `timestamp`      | string  | ISO 8601 UTC, e.g. `2026-05-14T13:00:00+00:00`.        |
| `forge_version`  | string  | Running forge package version (`forge.__version__`).   |
| `schema_version` | integer | Currently `1`. Bumped on any wire-shape change.        |
| `project_hash`   | string  | 16-char SHA-256 of the absolute project root.          |

Per-event fields below.

### Event vocabulary

#### `verify.ran` — `forge --verify` summary

Emitted once per `forge --verify` invocation, after the report renders.

| Field             | Type            | Description                                       |
|-------------------|-----------------|---------------------------------------------------|
| `worst`           | string          | `"clean"` / `"drift"` / `"conflict"`.             |
| `summary_counts`  | `dict[str,int]` | Status counts (`unchanged`, `user-modified`, …).  |
| `scope`           | string          | `"all"` / `"files"` / `"blocks"` / `"fragments"`. |
| `exit_code`       | integer         | Process exit code the dispatcher returns.         |

#### `verify.drift_detected` — per-record drift

Emitted once per drifted record (file or block). Suppressed for `unchanged` rows.

| Field         | Type   | Description                                            |
|---------------|--------|--------------------------------------------------------|
| `kind`        | string | `"file"` or `"block"`.                                 |
| `action`      | string | Record status (`user-modified`, `missing`, …).         |
| `rel_path`    | string | File record: project-relative POSIX path. **Stripped in `minimal`.** |
| `target_path` | string | Block record: `rel_path::feature_key:marker`. **Stripped in `minimal`.** |
| `fragment`    | string | Fragment name (when known). **Stripped in `minimal`.** |

#### `harvest.ran` — `forge --harvest` summary

Emitted once per `forge --harvest` invocation, after the bundle is built.

| Field                       | Type            | Description                                 |
|-----------------------------|-----------------|---------------------------------------------|
| `candidate_count_by_kind`   | `dict[str,int]` | Bucket counts by kind (`files`, `block`, …).|
| `candidate_count_by_risk`   | `dict[str,int]` | Bucket counts by risk (`safe-apply`, `needs-review`, `conflict`). |
| `entry_count`               | integer         | Total candidates emitted.                   |

#### `harvest.candidate_emitted` — per-candidate

Emitted once per `CandidatePatch` in the bundle.

| Field        | Type   | Description                                         |
|--------------|--------|-----------------------------------------------------|
| `kind`       | string | `"files"` / `"block"` / `"deps"` / `"env"`.         |
| `risk`       | string | `"safe-apply"` / `"needs-review"` / `"conflict"`.   |
| `fragment`   | string | Fragment name. **Stripped in `minimal`.**           |
| `rel_path`   | string | Project-relative POSIX path. **Stripped in `minimal`.** |

#### `update.ran` — `forge --update` summary

Emitted once per `forge --update` invocation, after the manifest is re-stamped.

| Field             | Type            | Description                                 |
|-------------------|-----------------|---------------------------------------------|
| `files_applied`   | integer         | Number of fragments re-applied.             |
| `blocks_applied`  | integer         | Count of user-modified records detected.    |
| `conflicts`       | integer         | Number of `.forge-merge` sidecars written.  |
| `entry_count`     | integer         | Number of fragments touched.                |
| `mode`            | string          | `"merge"` / `"skip"` / `"overwrite"`.       |
| `uninstalled`     | integer         | Number of uninstall outcomes recorded.      |

#### `update.conflict_emitted` — per-conflict

Emitted once per sidecar written. (Today there's no per-conflict metadata
available; the count is the only signal. A future PR may add path / fragment.)

| Field    | Type   | Description     |
|----------|--------|-----------------|
| `kind`   | string | `"file"`.       |
| `action` | string | `"conflict"`.   |

#### `accept_harvested.ran` — `forge --accept-harvested` summary

| Field                | Type            | Description                                |
|----------------------|-----------------|--------------------------------------------|
| `entries_by_action`  | `dict[str,int]` | Counts by per-entry action vocabulary.     |
| `entry_count`        | integer         | Total candidates in the bundle.            |
| `accepted`           | integer         | `restamped-baseline` count.                |
| `skipped`            | integer         | Combined skipped count.                    |
| `errored`            | integer         | Per-entry error count.                     |

#### `reapply_baseline.ran` — `forge --reapply-baseline` summary

| Field                | Type            | Description                                |
|----------------------|-----------------|--------------------------------------------|
| `entries_by_action`  | `dict[str,int]` | Counts by per-entry action vocabulary.     |
| `entry_count`        | integer         | Total records considered.                  |
| `accepted`           | integer         | `reset` count.                             |
| `skipped`            | integer         | Combined skipped count.                    |
| `errored`            | integer         | Per-record error count.                    |

#### `emit_pr.ran` — `forge --harvest --emit-pr=...` summary

| Field         | Type    | Description                                            |
|---------------|---------|--------------------------------------------------------|
| `mode`        | string  | `"branch"` or `"github"`.                              |
| `branch`      | string  | `harvest/<bundle_id>`. **Stripped in `minimal`.**      |
| `pr_url`      | string  | URL from `gh pr create` (github mode). **Stripped in `minimal`.** |
| `entry_count` | integer | Number of candidates considered.                       |
| `accepted`    | integer | `committed` count.                                     |
| `skipped`     | integer | Combined skipped (`skipped-unchanged` + `skipped-risk`). |
| `deferred`    | integer | `deferred` count.                                      |
| `errored`     | integer | `error` count.                                         |

#### `resolve.ran` — `forge --resolve` summary

| Field                | Type            | Description                                |
|----------------------|-----------------|--------------------------------------------|
| `entries_by_action`  | `dict[str,int]` | Counts by per-entry action vocabulary.     |
| `entry_count`        | integer         | Total sidecars walked.                     |
| `accepted`           | integer         | `accepted` count.                          |
| `rejected`           | integer         | `rejected` count.                          |
| `edited`             | integer         | `edited` count.                            |
| `skipped`            | integer         | `skipped` count.                           |
| `errored`            | integer         | Per-sidecar error count.                   |

#### `component.ran` — `forge --component-cmd ...` summary

Emitted by the Layer-1/2 component verbs (`list`, `scaffold`).

| Field    | Type   | Description                                       |
|----------|--------|---------------------------------------------------|
| `action` | string | The subcommand: `"list"` / `"scaffold"`.          |

#### `template.ran` — `forge --template-cmd ...` summary

Emitted by the Layer-3 template verbs (`list`).

| Field    | Type   | Description                                       |
|----------|--------|---------------------------------------------------|
| `action` | string | The subcommand: `"list"`.                         |

## 2. Opt-in mechanism

Forge reads the resolved mode from (in order, first match wins):

1. CLI: `--telemetry={off,local,remote}` (overrides env).
2. Env: `FORGE_TELEMETRY={off,local,remote}` (default: `off`).

Field scope:

1. CLI: `--telemetry-fields={minimal,full}` (overrides env).
2. Env: `FORGE_TELEMETRY_FIELDS={minimal,full}` (default: `full`).

Remote endpoint (env-only — URLs shouldn't end up in shell history):

* `FORGE_TELEMETRY_ENDPOINT=https://...` — used when `--telemetry=remote`.

Custom local sink (env-only):

* `FORGE_TELEMETRY_SINK=/path/to/telemetry.jsonl` — overrides
  `~/.forge/telemetry.jsonl`.

Examples:

```bash
# Local mode for one CI run
FORGE_TELEMETRY=local forge --verify

# Remote mode with full fields (assumes the operator trusts their endpoint)
FORGE_TELEMETRY=remote FORGE_TELEMETRY_ENDPOINT=https://collector.example.com/forge \
    forge --harvest

# Remote mode but minimal fields (paths and fragment names stripped)
FORGE_TELEMETRY=remote FORGE_TELEMETRY_ENDPOINT=https://collector.example.com/forge \
    FORGE_TELEMETRY_FIELDS=minimal forge --harvest

# CLI flag overrides env var
FORGE_TELEMETRY=local forge --telemetry=off --update    # no telemetry written
```

## 3. Privacy

* **`project_hash`** is a 16-char SHA-256 of the absolute project root path. It
  lets aggregators group events from the same project without learning the
  path. SHA-256 is preimage-resistant; the only data leakage is "same project
  vs different project".
* **`forge_version`** carries the running forge package version. Not user-
  identifying.
* **`minimal` field scope** strips every identifier-shaped field from the
  payload. Specifically:
  * Allowed top-level fields are explicitly listed in
    `forge.telemetry._MINIMAL_ALLOWED_FIELDS`. Any field not on the allowlist
    is dropped.
  * Stripped: `fragment`, `target_path`, `rel_path`, `sidecar_path`, `path`,
    `branch`, `pr_url`, `forge_repo`.
  * Kept: event envelope, bounded vocabulary fields (`kind`, `risk`, `action`,
    `mode`, `worst`), aggregate counts.
* **`full` field scope** keeps everything in the schemas above. It is the
  default for `local` sinks (operator-owned data is already operator-visible)
  and is **not recommended** for `remote` mode unless the operator controls
  the endpoint.
* **Remote endpoint contract**: forge POSTs `application/json` with a 2-second
  timeout. No retries (telemetry should fail fast). The operator's collector
  is responsible for its own auth — forge sends no auth headers. Failures log a
  warning to forge's structured logger (`forge.telemetry`) and never crash the
  generator.

## 4. Local sink

* Default path: `~/.forge/telemetry.jsonl` (override with `FORGE_TELEMETRY_SINK`).
* Format: one JSON object per line. UTF-8. Append-only.
* Rotation: when the active file exceeds 10MB, it's renamed to `telemetry.1.jsonl`
  and a fresh file starts. Up to 5 rotations are kept (`telemetry.1.jsonl` …
  `telemetry.5.jsonl`); the oldest is deleted.
* `forge --telemetry-export` streams every kept file (oldest rotation first,
  then the current file) to stdout. Useful for shipping to a collector after
  the fact, or for inspecting what forge has emitted.

## 5. Remote sink

* `FORGE_TELEMETRY=remote` requires `FORGE_TELEMETRY_ENDPOINT` to be set; the
  local sink is still written. Remote is **in addition to** local, not instead
  of it. (Easy "what did I send?" audit on the operator's host.)
* HTTP: `POST {endpoint}`, body is one event payload as JSON, header
  `Content-Type: application/json`. No auth headers — bring your own (e.g. a
  reverse proxy that injects them).
* Timeout: 2 seconds. No retries.
* Errors: logged at WARNING via `forge.logging`; never raised to the caller.
  The forge process continues even if every POST fails.
* Threading: the POST runs on a daemon worker thread so the main CLI dispatch
  never blocks on network IO.

## 6. Disabling

* Set `FORGE_TELEMETRY=off` (or omit the variable; off is the default).
* Or pass `--telemetry=off` on any forge invocation to override an env var.
* To delete existing local data:

  ```bash
  rm -rf ~/.forge/telemetry.jsonl ~/.forge/telemetry.*.jsonl
  ```

  Forge never writes anywhere else (no `/tmp` spool, no system journal).

## 7. `--log-json` event stream (agent-facing trace)

Distinct from the telemetry sink: `--log-json` (or `FORGE_LOG_FORMAT=json`)
flips forge's own structured logger from text to NDJSON on **stderr**. This
is the seam an agent driving `forge new …` consumes to build a live trace
of generation — every phase wrapped in `phase_timer` emits two events
(`phase.start` is implicit; the closing record carries `duration_ms` and
`status`), plus ad-hoc `log_event(...)` calls scattered through plugins
and codegen.

The flag is **off by default** — nothing on stderr changes shape unless an
operator explicitly opts in.

### Envelope

Every NDJSON line has the same outer shape:

| Field            | Type    | Description                                                                |
|------------------|---------|----------------------------------------------------------------------------|
| `ts`             | string  | ISO 8601 UTC of when the record was created.                               |
| `level`          | string  | `DEBUG` / `INFO` / `WARNING` / `ERROR`.                                    |
| `logger`         | string  | The originating logger, e.g. `forge.generator` or `forge.plugins`.         |
| `message`        | string  | Human-readable message (usually equal to `event`).                         |
| `event`          | string  | Stable dotted event name. **Filter on this.**                              |
| `correlation_id` | string  | UUID stamped once per CLI invocation; identical across every record from the same `forge` process. |
| `duration_ms`    | integer | Present on `phase_timer` closing records.                                  |
| `status`         | string  | `"ok"` on success or `"failed"` on exception (phase records).              |
| `exc_info`       | string  | Traceback when the record carries an exception.                            |
| _arbitrary_      | any     | Call-site fields (e.g. `backend=p1-svc`, `language=python`, `fragment_count=12`). |

The `correlation_id` field is the v2 Theme 10 contract: an NDJSON consumer
parsing interleaved log streams (multiple `forge` processes on the same
stderr, plugin subprocesses, CI fan-out) groups events by this UUID.

### Phase events emitted by the generator

`forge.generator` wraps each phase in `phase_timer`; on exit the closing
record is emitted at INFO (or WARNING with `status="failed"` on exception).

| Event                              | Extra fields                                  | Origin                          |
|------------------------------------|-----------------------------------------------|---------------------------------|
| `generate.resolve`                 | —                                             | capability resolver pass        |
| `generate.validate_plan`           | —                                             | static pre-flight validation    |
| `generate.copier.backend`          | `backend`, `language`                         | per-backend Copier render       |
| `generate.apply_features`          | `backend`, `language`, `fragment_count`       | per-backend fragment injection  |
| `generate.toolchain.install`       | `backend`, `language`                         | toolchain install hook          |
| `generate.toolchain.verify`        | `backend`, `language`                         | toolchain verify hook           |
| `generate.copier.frontend`         | `framework`                                   | frontend Copier render          |
| `generate.compose.render`          | —                                             | docker-compose render           |
| `generate.apply_project_features`  | —                                             | project-scope fragment pass     |
| `generate.codegen`                 | —                                             | schema-first codegen pipeline   |
| `generate.write_forge_toml`        | —                                             | provenance manifest write       |

Additional events fire from elsewhere in the codebase (`plugin.loaded`,
`fragment.applied`, `injection.fallback_text`, etc.); the table above
covers the per-phase wrappers in `forge/generator.py` so an agent can build
a full timeline of a `forge new …` invocation.

### Example

```bash
forge new --quiet --yes --no-docker --log-json \
  --output-dir /tmp/probe --project-name probe \
  --backend-language python 2> trace.jsonl
```

```jsonl
{"ts":"2026-05-17T12:00:00+00:00","level":"INFO","logger":"forge.generator","message":"generate.resolve","event":"generate.resolve","duration_ms":18,"status":"ok","correlation_id":"f1a2…"}
{"ts":"2026-05-17T12:00:00+00:00","level":"INFO","logger":"forge.generator","message":"generate.validate_plan","event":"generate.validate_plan","duration_ms":2,"status":"ok","correlation_id":"f1a2…"}
{"ts":"2026-05-17T12:00:03+00:00","level":"INFO","logger":"forge.generator","message":"generate.copier.backend","event":"generate.copier.backend","backend":"probe","language":"python","duration_ms":3201,"status":"ok","correlation_id":"f1a2…"}
…
```

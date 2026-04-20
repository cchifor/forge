# RFC-004: Release rehearsal before 1.0.0

- Status: Accepted
- Author: forge team
- Created: 2026-04-20
- Updated: 2026-04-20
- Target: 1.0.0rc1

## Summary

Before tagging `v1.0.0`, forge publishes every package to its test registry (TestPyPI / npm `alpha` dist-tag / pub.dev `--dry-run`) via a rehearsal dispatch of the release workflow. This catches registry credential drift, build-config bugs, and cross-package version mismatches before they hit the stable channel.

## Motivation

Four packages publish in lockstep (PyPI `forge`, npm `@forge/canvas-vue`, npm `@forge/canvas-svelte`, pub.dev `forge_canvas`). Any of the following would fail a real 1.0.0 tag and leave the ecosystem in a half-shipped state:

- OIDC trusted-publishing misconfiguration on PyPI
- Missing `NPM_AUTH_TOKEN` or `PUB_DEV_CREDENTIALS` secrets after a rotation
- A version-string typo in one `package.json` vs `pubspec.yaml`
- Build failure on any package the test suite didn't cover (e.g. Vite library build finds a type error the `npm run typecheck` pass missed)
- A registry auth change (npm 2FA required, PyPI trusted-publisher policy) that nobody noticed in the doc scan

A rehearsal catches all of these cheaply. We run one before every RC.

## Design

### Workflow triggers

`.github/workflows/release.yml` accepts two trigger modes:

**1. Tag push (production)** — `on: push: tags: [v*.*.*]`. Every job publishes to its real registry. Fails on any registry error.

**2. Manual dispatch (rehearsal)** — `workflow_dispatch` with inputs:

| Input | Type | Default | Effect |
|---|---|---|---|
| `dry_run` | boolean | `true` | When `true`, build every package but skip registry pushes. Artefacts uploaded to the workflow run for inspection. |
| `target` | choice | `testpypi-only` | `testpypi-only` — only PyPI → TestPyPI. `all-testing` — TestPyPI + npm alpha tag + pub.dev dry-run. `stable` — real PyPI + npm latest + pub.dev publish (honours `dry_run` still). |

### Rehearsal matrix

| Stage | What runs | Run frequency |
|---|---|---|
| Per-PR sanity | `npm run build && npm run typecheck` for each canvas package; `uv build` for forge; `flutter analyze` | Every PR (already in `ci.yml`) |
| Pre-RC rehearsal | `workflow_dispatch` with `dry_run=true, target=all-testing` | Before cutting any RC |
| Pre-1.0.0 rehearsal | `workflow_dispatch` with `dry_run=false, target=all-testing` | Before the v1.0.0 tag push |
| Production | Tag push | Once per release |

### Version-lockstep check

The canvas packages must all report the same semver major+minor+patch before a stable publish. A pre-publish step in each job asserts:

```bash
# Python
python -c "import tomllib; print(tomllib.loads(open('pyproject.toml','rb').read())['project']['version'])"

# npm
node -p "require('./package.json').version"

# pub.dev
grep '^version:' pubspec.yaml | awk '{print $2}'
```

The numbers must match for stable publishes; pre-releases (`alpha.N`, `beta.N`, `rc.N`) can diverge since packages may need extra alphas for canvas-specific work.

### Rollback plan

- **PyPI** doesn't allow unpublishing, but we can yank a release from the trove (version still exists, no longer installable without pinning). Document the yank in the GitHub release's "Post-release notes" section.
- **npm** supports `npm unpublish` within 72 hours; beyond that, `npm deprecate` is the tool.
- **pub.dev** publishes are immutable. Bad releases require a follow-up version + a deprecation notice.

Because of these asymmetries, the rehearsal matrix weights PyPI failures heaviest — a broken TestPyPI publish blocks the RC until it's fixed.

### Credentials

| Registry | Mechanism | Required secret |
|---|---|---|
| PyPI | OIDC trusted publishing | _none_ — binds to the repository |
| TestPyPI | OIDC trusted publishing | _none_ |
| npm | `NODE_AUTH_TOKEN` env var | `NPM_AUTH_TOKEN` in `release` environment |
| pub.dev | Credentials JSON via `~/.config/dart/pub-credentials.json` | `PUB_DEV_CREDENTIALS` in `release` environment |

A doc-drift check at the top of the workflow logs every required secret and fails fast on missing ones so a credential rotation doesn't corrupt the rehearsal.

## Alternatives considered

### No rehearsal — just push the tag

Saves one manual workflow dispatch. Rejected because each recovery from a half-shipped release costs far more than the 10 minutes of rehearsal.

### Separate workflow for each package

Cleaner code per-file but loses the lockstep ordering invariant (PyPI ships first because the CLI is the entry point). Rejected.

### Automated nightly rehearsal

Could run `workflow_dispatch` nightly via a cron schedule. Appealing but expensive on CI minutes and TestPyPI has rate limits. Deferred — may revisit if the per-RC manual trigger drifts.

## Drawbacks

- Requires maintainer discipline — nothing auto-enforces "run the rehearsal before tagging stable".
- TestPyPI publishes accumulate forever; periodic cleanup is a chore.

## Open questions

- **Post-1.0 cadence**: once forge is stable, should rehearsal run automatically for every PR targeting `main`? Likely yes for security-affected PRs; TBD for the general case.
- **Canvas package version divergence**: if only `@forge/canvas-vue` has a bugfix, do we publish `canvas-vue@1.0.1` alone or bump all three to stay visually in lockstep? Current answer: per-package versioning allowed for patches, lockstep required for minor+major.

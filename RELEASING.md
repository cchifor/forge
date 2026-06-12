# Releasing forge

## Distribution model — GitHub-only

forge is **not published to any package registry** (no PyPI, npm, or pub.dev).
The source lives in this repository and the canonical install path is the
**`./install`** script, which runs:

```sh
uv tool install git+https://github.com/cchifor/forge.git
```

i.e. it builds and installs `forge` directly from the GitHub source. To install
a specific tagged version instead of `main`:

```sh
uv tool install "git+https://github.com/cchifor/forge.git@v1.2.0"
```

A "release" here is therefore just a **git tag + a GitHub Release** carrying the
built artifacts and changelog notes for convenience — nothing is uploaded to a
registry. (See [docs/rfcs/RFC-003](docs/rfcs/RFC-003-package-naming.md), now
superseded, for why registry publishing was dropped.)

## Versioning

We follow [Semantic Versioning 2.0](https://semver.org/) with PEP440-style
pre-release identifiers (`1.2.0a1`, `1.2.0b1`, `1.2.0rc1`, `1.2.0`). The single
source of truth for the version is **`forge/__init__.py`** (`__version__`);
`pyproject.toml` reads it dynamically. The CLI exposes it via `forge --version`.

## Release process

1. **CHANGELOG.md** — ensure the `## [Unreleased]` section is complete and
   non-empty (every breaking change under `### Breaking`). The release workflow
   extracts this section for the GitHub Release notes and fails if it's empty.
2. **Bump the version** — set `__version__` in `forge/__init__.py` to the
   release version (no `v` prefix), commit on `main`.
3. **Tag** — `git tag -a v1.2.0 -m "forge 1.2.0"` (pre-releases: `v1.2.0rc1`).
4. **Push the tag** — `git push origin v1.2.0`. This triggers
   [`release.yml`](.github/workflows/release.yml), which:
   - verifies the tag matches `__version__` (fails closed on mismatch),
   - builds the sdist + wheel,
   - generates a CycloneDX SBOM,
   - creates a **GitHub Release** (marked pre-release for `aN`/`bN`/`rcN`/`.devN`
     tags) with the changelog notes and attaches `dist/*` + the SBOM.
5. **Verify** the GitHub Release looks right and `./install` works from a clean
   machine (the [`install-test`](.github/workflows/install-test.yml) workflow
   smoke-tests this on ubuntu + macOS).

There is **no registry publish step, no dry-run rehearsal, and no publish
credentials** — those were removed when distribution moved to GitHub-only.

## Breaking-change policy

Every breaking change must:

1. Appear under `### Breaking` in `CHANGELOG.md`.
2. Include a migration note in `UPGRADING.md`.
3. Ship a `forge migrate-<name>` codemod when mechanically applicable, or
   documented manual steps otherwise.

Dropping a supported Python version is a breaking change.

## Emergency / security releases

1. Branch from `main`: `fix/security-<id>`.
2. Fix, add a regression test, land via PR.
3. Bump `__version__`, update CHANGELOG, tag the patch release, push the tag.
4. Document the advisory under `docs/security-advisories/`.

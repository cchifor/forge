"""Codemod: cut over from forge's legacy Keycloak-direct auth stack
to the platform-auth model (Phase 10 of the auth-port roadmap).

The codemod is the *atomic ship-it bundle* that brings an existing
forge-generated project across the 1.1 → 1.2 boundary. See the
architectural reference at ``docs/auth-architecture.md`` for the
target model and ``UPGRADING.md`` §"1.1 → 1.2 — auth-stack rebuild"
for the user-facing playbook.

This pass does the *project-side* work that ``forge --update`` can't
infer from fragment provenance alone:

  1. **Detect** legacy state — ``python-keycloak`` in ``pyproject.toml``,
     presence of ``service/security/providers/keycloak.py``, header-only
     ``middleware/tenant.{ts,rs}``, missing ``packages/platform-auth*/``.
     If the project is *already* on platform-auth (or has no auth at
     all), the codemod skips with a clear reason.

  2. **Rename env vars** in ``.env`` / ``.env.example`` /
     ``docker-compose.yml``: ``KEYCLOAK_CLIENT_ID`` →
     ``GATEKEEPER_CLIENT_ID``, ``KEYCLOAK_CLIENT_SECRET`` →
     ``GATEKEEPER_CLIENT_SECRET``,
     ``APP__SECURITY__AUTH__SERVER_URL`` → ``GATEKEEPER_ISSUER``,
     etc. Drops keys that have moved owner (``KEYCLOAK_REALM`` —
     subsumed by ``KEYCLOAK_BASE_URL``;
     ``APP__SECURITY__AUTH__REALM`` — subsumed by single-issuer
     ``GATEKEEPER_ISSUER``).

  3. **Drop legacy Python deps** — remove ``python-keycloak`` from
     each Python service's ``pyproject.toml``.

  4. **Remove legacy provider modules** — ``service/security/providers/``
     directory (``keycloak.py``, ``dev.py``). The new
     ``platform_auth_python_middleware`` fragment ships the
     replacement modules at canonical paths.

  5. **Add new env vars** — ``SESSION_FERNET_KEY``,
     ``DEFAULT_IDLE_TIMEOUT_SECONDS``, ``DEFAULT_ABSOLUTE_TIMEOUT_SECONDS``,
     ``SESSION_WARN_AT_SECONDS``, ``INTERNAL_TOKEN_AUDIENCE``,
     ``KEY_BACKEND``, ``SIGNING_KEY_DIR``,
     ``SERVICE_REGISTRY_PATH``, ``SVC_AUTH_BACKEND`` — with safe
     defaults documented inline.

The fragment-file work (shipping ``packages/platform-auth*/``, the new
gatekeeper sources, the per-language middleware fragments) is handled
by the existing ``forge --update`` infrastructure once the Phase 2
cutover wires ``auth.mode=generate`` to enable the new fragments.
This codemod runs *before* the user invokes ``forge --update`` so
the env vars + deps are clean by the time the new files land.

Re-runnable: a second pass detects the post-migration steady state
and skips with ``applied=False``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from forge.migrations.base import MigrationReport

NAME = "auth-keycloak-to-platform-auth"
FROM = "1.1.0"
TO = "1.2.0"
DESCRIPTION = (
    "Cut over from the legacy Keycloak-direct auth stack to the platform-auth model "
    "(BFF Redis sessions + Gatekeeper-as-sole-token-authority + per-language SDKs)."
)


# Env vars that *rename* — old key on the left, new key on the right.
# When the new key already exists, the old key is dropped without
# overwriting (user-managed precedence).
ENV_RENAMES: tuple[tuple[str, str], ...] = (
    ("APP__SECURITY__AUTH__SERVER_URL", "GATEKEEPER_ISSUER"),
    ("KEYCLOAK_CLIENT_ID", "GATEKEEPER_CLIENT_ID"),
    ("KEYCLOAK_CLIENT_SECRET", "GATEKEEPER_CLIENT_SECRET"),
)

# Env vars that go away entirely — the value is encoded elsewhere
# (e.g., realm in the base URL path) or no longer applicable.
ENV_REMOVALS: tuple[str, ...] = (
    "KEYCLOAK_REALM",
    "APP__SECURITY__AUTH__REALM",
)

# Env vars to add (with safe defaults). Skipped if already present.
ENV_ADDITIONS: tuple[tuple[str, str, str], ...] = (
    (
        "INTERNAL_TOKEN_AUDIENCE",
        "forge-services",
        "aud claim on Gatekeeper-minted internal JWTs",
    ),
    (
        "DEFAULT_IDLE_TIMEOUT_SECONDS",
        "1800",
        "BFF session idle timeout (30 min)",
    ),
    (
        "DEFAULT_ABSOLUTE_TIMEOUT_SECONDS",
        "43200",
        "BFF session absolute timeout (12 h)",
    ),
    (
        "SESSION_WARN_AT_SECONDS",
        "60",
        "SPA pre-warning modal threshold (seconds)",
    ),
    (
        "KEY_BACKEND",
        "file",
        "Gatekeeper signing-key backend (file | aws_kms | vault)",
    ),
    (
        "SIGNING_KEY_DIR",
        "/run/secrets/gatekeeper-signing",
        "Filesystem path where gatekeeper-keygen writes ECDSA P-256 keys",
    ),
    (
        "SERVICE_REGISTRY_PATH",
        "/run/secrets/gatekeeper-service-registry/service_registry.yaml",
        "argon2id-hashed S2S client secrets",
    ),
    (
        "SVC_AUTH_BACKEND",
        "preshared",
        "S2S auth backend (preshared | k8s | mtls)",
    ),
    (
        "SESSION_TIMEOUT_ENABLED",
        "true",
        "Idle/absolute timeout enforcement; flip to false to disable",
    ),
)

# Python deps to drop from per-service pyproject.toml.
LEGACY_PYTHON_DEPS: tuple[str, ...] = ("python-keycloak",)

# Legacy files to remove (relative to each Python service root).
LEGACY_PYTHON_FILES: tuple[str, ...] = (
    "src/service/security/providers/keycloak.py",
    "src/service/security/providers/dev.py",
)


@dataclass(frozen=True)
class _LegacySignals:
    """Fingerprint of a legacy auth project."""

    has_keycloak_dep: bool
    has_legacy_provider: bool
    has_old_env_keys: bool
    has_platform_auth_sdk: bool

    @property
    def is_legacy(self) -> bool:
        # Either old deps OR old provider OR old env keys, AND no SDK
        # already shipped. The SDK-already-shipped case means an
        # earlier codemod run partially applied — let the user resolve
        # via forge --plan-update.
        return (
            self.has_keycloak_dep or self.has_legacy_provider or self.has_old_env_keys
        ) and not self.has_platform_auth_sdk


def _detect_legacy(project_root: Path) -> _LegacySignals:
    """Survey the project for legacy-stack signals.

    Run before any rewrites — drives the skip-or-apply decision so
    ``forge migrate auth-keycloak-to-platform-auth --dry-run`` can
    produce a useful "would do nothing" report.
    """
    has_keycloak_dep = False
    services_root = project_root / "services"
    if services_root.is_dir():
        for service_dir in services_root.iterdir():
            pyproject = service_dir / "pyproject.toml"
            if not pyproject.is_file():
                continue
            text = pyproject.read_text(encoding="utf-8")
            if any(dep in text for dep in LEGACY_PYTHON_DEPS):
                has_keycloak_dep = True
                break

    has_legacy_provider = False
    if services_root.is_dir():
        for service_dir in services_root.iterdir():
            if (
                service_dir / "src" / "service" / "security" / "providers" / "keycloak.py"
            ).is_file():
                has_legacy_provider = True
                break

    has_old_env_keys = False
    for candidate in (
        project_root / ".env",
        project_root / ".env.example",
        project_root / "docker-compose.yml",
        project_root / "docker-compose.yaml",
    ):
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8")
        # Legacy keys appear as ``.env`` ``KEY=`` or YAML ``KEY:`` —
        # accept either separator so compose-only projects are detected.
        if any(
            re.search(rf"^\s*{re.escape(old)}\s*(=|:)", text, re.MULTILINE)
            for old, _ in ENV_RENAMES
        ):
            has_old_env_keys = True
            break
        if any(
            re.search(rf"^\s*{re.escape(removed)}\s*(=|:)", text, re.MULTILINE)
            for removed in ENV_REMOVALS
        ):
            has_old_env_keys = True
            break

    sdk_path = project_root / "packages" / "platform-auth"
    has_platform_auth_sdk = sdk_path.is_dir()

    return _LegacySignals(
        has_keycloak_dep=has_keycloak_dep,
        has_legacy_provider=has_legacy_provider,
        has_old_env_keys=has_old_env_keys,
        has_platform_auth_sdk=has_platform_auth_sdk,
    )


# Matches either ``.env`` ``KEY=value`` or YAML ``KEY: value`` (the
# indented service-environment shape forge writes into
# docker-compose.yml). Group 1 = leading indent, group 2 = key,
# group 3 = separator (``=`` or ``:``).
_ENV_LINE = re.compile(r"^(\s*)([A-Z_][A-Z0-9_]*)(=|:)")


def _rewrite_env_file(
    path: Path,
    dry_run: bool,
    changes: list[str],
) -> None:
    """Apply ENV_RENAMES + ENV_REMOVALS + ENV_ADDITIONS to one .env-style file.

    Also handles the YAML ``KEY: value`` form used by
    ``docker-compose.yml`` service-environment blocks, so stale
    Keycloak env doesn't survive in compose after migration.

    Preserves comments, blank lines, indentation, and quoting style.
    New keys are appended at the end of the file with a single
    blank-line separator if any keys were added. Additions are only
    appended for ``.env``-style files (``=`` separator); a YAML compose
    file is rewritten in place but not grown with bare ``KEY=value``
    lines, which would corrupt its structure.
    """
    if not path.is_file():
        return

    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=False)

    is_compose = path.name in ("docker-compose.yml", "docker-compose.yaml")

    # Two-pass: first collect every key the file defines so we can
    # detect the "user already set both old AND new" case regardless
    # of ordering.
    pre_existing_keys: set[str] = set()
    for line in lines:
        match = _ENV_LINE.match(line)
        if match:
            pre_existing_keys.add(match.group(2))

    new_lines: list[str] = []
    written_keys: set[str] = set()

    for line in lines:
        # Capture key names — keep blank/comment lines verbatim.
        match = _ENV_LINE.match(line)
        if not match:
            new_lines.append(line)
            continue
        indent, key, sep = match.group(1), match.group(2), match.group(3)
        # Reconstruct the exact key+separator prefix so renames preserve
        # the file's native form (``=`` vs ``: ``) and indentation.
        prefix = f"{indent}{key}{sep}"

        # Renames first.
        renamed = False
        for old, new in ENV_RENAMES:
            if key == old:
                # User already set the canonical key elsewhere in the
                # file? Drop the alias without overwriting — the user's
                # explicit canonical wins.
                if new in pre_existing_keys:
                    changes.append(
                        f"{path.name}: dropped {old}{sep} (canonical {new}{sep} already set)"
                    )
                else:
                    new_lines.append(re.sub(rf"^{re.escape(prefix)}", f"{indent}{new}{sep}", line))
                    written_keys.add(new)
                    changes.append(f"{path.name}: renamed {old}{sep} → {new}{sep}")
                renamed = True
                break
        if renamed:
            continue

        # Removals.
        if key in ENV_REMOVALS:
            changes.append(f"{path.name}: dropped {key}{sep} (no longer applicable)")
            continue

        new_lines.append(line)
        written_keys.add(key)

    # Additions — append unset defaults at the bottom of the file.
    # Use the pre-existing set (what the user originally had) so we
    # don't double-add anything just because a rename produced the key.
    # Skip for YAML compose files: appending bare ``KEY=value`` lines
    # would corrupt structure, and the new keys belong in service blocks
    # the user maintains, not at file scope.
    additions_added: list[str] = []
    for env_key, default, comment in () if is_compose else ENV_ADDITIONS:
        if env_key in pre_existing_keys or env_key in written_keys:
            continue
        if not additions_added:
            # One blank line before the additions block.
            if new_lines and new_lines[-1] != "":
                additions_added.append("")
            additions_added.append("# Added by forge migrate auth-keycloak-to-platform-auth")
        additions_added.append(f"# {comment}")
        additions_added.append(f"{env_key}={default}")
        changes.append(f"{path.name}: added {env_key}={default}")
    new_lines.extend(additions_added)

    new_text = "\n".join(new_lines)
    # Preserve trailing newline if the original had one.
    if original.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"

    if new_text == original:
        return
    if not dry_run:
        path.write_text(new_text, encoding="utf-8")


def _strip_python_keycloak_dep(
    pyproject_path: Path,
    dry_run: bool,
    changes: list[str],
) -> None:
    """Drop ``python-keycloak`` from a service's pyproject.toml.

    Two TOML idioms covered:

    1. Multi-line array (one dep per line, the usual hatchling shape) —
       remove the whole line.
    2. Single-line / inline array (``dependencies = ["a", "b", "c"]``) —
       remove just the entry + any leading/trailing comma + whitespace.

    Doesn't use ``tomlkit`` because preserving the file's original
    formatting (spacing, comments, alignment) matters more than typed
    parsing for this single-purpose rewrite.
    """
    if not pyproject_path.is_file():
        return
    original = pyproject_path.read_text(encoding="utf-8")
    new_text = original
    for dep in LEGACY_PYTHON_DEPS:
        # 1) Whole-line dep entry (multi-line array).
        whole_line = re.compile(
            rf'^\s*"{re.escape(dep)}[^"]*",?\s*$\n',
            re.MULTILINE,
        )
        if whole_line.search(new_text):
            new_text = whole_line.sub("", new_text)
            changes.append(
                f"{pyproject_path.relative_to(pyproject_path.parents[2])}: removed dep '{dep}'"
            )
            continue
        # 2) Inline array — match the entry and the comma/whitespace
        # adjacent to it. Two passes: try `, "dep>=x"` first (mid- /
        # end-of-array), then `"dep>=x", ` (start-of-array).
        inline_after = re.compile(rf',\s*"{re.escape(dep)}[^"]*"')
        inline_before = re.compile(rf'"{re.escape(dep)}[^"]*",\s*')
        if inline_after.search(new_text):
            new_text = inline_after.sub("", new_text, count=1)
            changes.append(
                f"{pyproject_path.relative_to(pyproject_path.parents[2])}: removed dep '{dep}' (inline array)"
            )
        elif inline_before.search(new_text):
            new_text = inline_before.sub("", new_text, count=1)
            changes.append(
                f"{pyproject_path.relative_to(pyproject_path.parents[2])}: removed dep '{dep}' (inline array)"
            )
        else:
            # Single-element array — the entry is the entire array
            # contents. Match `"dep>=x"` with no leading/trailing comma.
            sole = re.compile(rf'"{re.escape(dep)}[^"]*"')
            if sole.search(new_text):
                new_text = sole.sub("", new_text, count=1)
                changes.append(
                    f"{pyproject_path.relative_to(pyproject_path.parents[2])}: removed dep '{dep}' (sole entry)"
                )
    if new_text != original and not dry_run:
        pyproject_path.write_text(new_text, encoding="utf-8")


def _remove_legacy_provider_files(
    services_root: Path,
    dry_run: bool,
    changes: list[str],
) -> None:
    """Remove the legacy ``service/security/providers/{keycloak,dev}.py``
    modules from each Python service. The new
    ``platform_auth_python_middleware`` fragment ships replacement
    modules at canonical paths.
    """
    if not services_root.is_dir():
        return
    for service_dir in services_root.iterdir():
        for relative in LEGACY_PYTHON_FILES:
            target = service_dir / relative
            if not target.is_file():
                continue
            if not dry_run:
                target.unlink()
            changes.append(f"{service_dir.name}: removed legacy {relative}")
        # Try to remove the now-empty providers/ dir.
        providers_dir = service_dir / "src" / "service" / "security" / "providers"
        if providers_dir.is_dir() and not any(providers_dir.iterdir()):
            if not dry_run:
                providers_dir.rmdir()
            changes.append(f"{service_dir.name}: removed empty providers/ directory")


def run(project_root: Path, dry_run: bool, quiet: bool) -> MigrationReport:
    """Execute the auth-stack migration.

    The codemod is *idempotent* — re-running on a post-migrated project
    produces ``applied=False`` with a clear ``skipped_reason``. The
    file-fragment work (shipping new SDK trees, gatekeeper sources,
    middleware modules) is handled by ``forge --update`` *after* this
    pass; the user's expected workflow is:

    .. code-block:: bash

        forge --plan-migrate auth-keycloak-to-platform-auth   # dry-run preview
        forge --migrate      auth-keycloak-to-platform-auth   # apply
        forge --update                                         # ship new fragments
        docker compose up --build                              # boot the new stack
    """
    signals = _detect_legacy(project_root)
    if signals.has_platform_auth_sdk and not (
        signals.has_keycloak_dep or signals.has_legacy_provider
    ):
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=(
                f"packages/platform-auth/ already present and no legacy signals — "
                f"migration appears already applied at {project_root}"
            ),
        )
    if not signals.is_legacy:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=(
                f"no legacy auth signals detected at {project_root} "
                f"(no python-keycloak dep, no legacy provider modules, no old env keys)"
            ),
        )

    changes: list[str] = []
    if not quiet:
        print(f"  [{NAME}] Migrating {project_root} from Keycloak-direct → platform-auth")
    if dry_run and not quiet:
        print(f"  [{NAME}] DRY RUN — no files will be modified")

    # 1. Env-var work in .env / .env.example / docker-compose.yml.
    for env_file in (
        project_root / ".env",
        project_root / ".env.example",
        project_root / "docker-compose.yml",
        project_root / "docker-compose.yaml",
    ):
        _rewrite_env_file(env_file, dry_run, changes)

    # 2. Drop python-keycloak from each Python service's pyproject.
    services_root = project_root / "services"
    if services_root.is_dir():
        for service_dir in services_root.iterdir():
            _strip_python_keycloak_dep(service_dir / "pyproject.toml", dry_run, changes)

    # 3. Remove legacy provider modules.
    _remove_legacy_provider_files(services_root, dry_run, changes)

    # 4. Final guidance — what to do next.
    next_steps = (
        "Run `forge --update` to ship the new packages/platform-auth*/ trees, "
        "the upgraded infra/gatekeeper/, and the per-language middleware "
        "fragments. Then `docker compose up --build` to boot the new stack. "
        "See UPGRADING.md §'1.1 → 1.2' for the full playbook."
    )
    if not changes:
        return MigrationReport(
            name=NAME,
            applied=False,
            skipped_reason=(
                f"detected legacy signals but no rewrites applied — investigate: {signals!r}"
            ),
        )

    if not quiet and not dry_run:
        print(f"  [{NAME}] Applied {len(changes)} change(s); next: {next_steps}")
    return MigrationReport(
        name=NAME,
        applied=not dry_run,
        changes=changes,
    )

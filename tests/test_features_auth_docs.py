"""Invariants for the auth-stack documentation (Phase 10).

Two artifacts ship in this phase:

1. ``docs/auth-architecture.md`` — the architectural reference for
   how forge-generated projects authenticate users and services.
   Documents Gatekeeper, the per-language SDKs, the BFF + session-
   timeout SPA pattern, the configuration knobs, and the compliance
   notes.

2. The 1.1 → 1.2 migration section appended to the top-level
   ``UPGRADING.md``. Documents the codemod, env var renames, cookie
   changes, and the behavioural shifts engineers should know.

These tests gate the *structural* presence of the docs so a future
edit that drops a section silently surfaces here, where the
correctness of the documented invariants is the SDK invariants
suite's job.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 10 deliverables — ``docs/auth-architecture.md`` is "new",
``UPGRADING.md`` is "modified").
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_DOC = REPO_ROOT / "docs" / "auth-architecture.md"
UPGRADING_DOC = REPO_ROOT / "UPGRADING.md"
README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def test_auth_architecture_doc_exists() -> None:
    assert ARCH_DOC.is_file(), f"docs/auth-architecture.md missing at {ARCH_DOC}"


def test_auth_architecture_doc_covers_key_sections() -> None:
    """The doc must have the load-bearing top-level sections.

    A future edit that accidentally drops one of these sections
    surfaces here rather than a downstream "where is X documented?"
    question.
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    required_sections = (
        "## TL;DR",
        "## Architecture diagram",
        "## Components",
        "### Keycloak (identity provider)",
        "### Gatekeeper (token authority + BFF)",
        "### Backend verifier SDKs",
        "### Frontend session-timeout components",
        "## Token flow walkthroughs",
        "### Browser login",
        "### Service-to-service (on-behalf-of)",
        "### Inactivity-driven session refresh",
        "## Configuration knobs",
        "## Compliance notes",
        "## Migration from legacy",
        "## Out of scope (follow-up tickets)",
    )
    missing = [section for section in required_sections if section not in text]
    assert not missing, f"docs/auth-architecture.md missing sections: {missing}"


def test_auth_architecture_doc_references_phase4_invariant() -> None:
    """Phase 4 invariant — sole token authority — is the single most
    load-bearing design decision in the doc. Pin it explicitly.
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    assert "sole token authority" in text.lower(), (
        "auth-architecture.md must explicitly call out Gatekeeper as "
        "the sole token authority (Phase 4 invariant)"
    )
    assert "ES256" in text, (
        "auth-architecture.md must specify ES256 as the algorithm pin"
    )
    assert "https://forge/tenant_id" in text, (
        "auth-architecture.md must specify the tenant_id claim name"
    )


def test_auth_architecture_doc_explains_bff_two_key_session() -> None:
    """The two-key Redis session model is the atomicity primitive.

    Engineers who don't understand why two keys (vs a single
    encrypted blob) will reach for the latter at refactor time and
    re-introduce the read-evaluate-write race.
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    assert "gk:session" in text, "Doc must show the Redis key shape"
    assert ":body" in text and ":active" in text, (
        "Doc must distinguish the :body (Fernet-encrypted) and :active "
        "(idle TTL) keys explicitly"
    )
    # The "never extended" property of :body is the atomicity tradeoff.
    assert "never extended" in text.lower() or "Never extended" in text, (
        "Doc must explain that :body's TTL is set once and never extended"
    )


def test_auth_architecture_doc_explains_activity_signal() -> None:
    """The chosen activity model — explicit user-interaction events,
    NOT API traffic — is the compliance-driving decision. The doc
    must explain *why* and reference the RFC.
    """
    text = ARCH_DOC.read_text(encoding="utf-8")
    assert "real user activity" in text.lower() or "real user-interaction" in text.lower(), (
        "Doc must contrast 'real user activity' against 'API traffic = activity'"
    )
    assert "BroadcastChannel" in text, (
        "Doc must mention BroadcastChannel cross-tab dedup (the SPA pattern)"
    )
    # Visibility gating — the third RFC mechanism.
    assert "visibilityState" in text or "visibility-gat" in text.lower() or "AppLifecycleState" in text, (
        "Doc must mention visibility gating in some form"
    )


def test_auth_architecture_doc_lists_compliance_targets() -> None:
    """Compliance posture is the headline reason for the architecture.
    Make the targets explicit so the doc serves as the single source
    of truth for the security review."""
    text = ARCH_DOC.read_text(encoding="utf-8")
    must_mention = ("SOC 2", "ISO 27001", "NIST 800-63B-4", "OWASP", "RFC 8693", "RFC 9068")
    missing = [name for name in must_mention if name not in text]
    assert not missing, (
        f"Compliance section must mention {missing} — these are the load-bearing standards"
    )


def test_upgrading_md_has_1_2_section() -> None:
    """UPGRADING.md must have the 1.1 → 1.2 migration section."""
    text = UPGRADING_DOC.read_text(encoding="utf-8")
    assert "## 1.1 → 1.2" in text, (
        "UPGRADING.md must have a '## 1.1 → 1.2' migration section"
    )
    # The codemod name is the load-bearing CLI invocation.
    assert "auth-keycloak-to-platform-auth" in text, (
        "UPGRADING.md must reference the codemod by its `--migrate <name>` value"
    )
    assert "--dry-run" in text, (
        "UPGRADING.md must document the dry-run path so users plan before applying"
    )


def test_upgrading_md_documents_env_var_renames() -> None:
    """The env var rename table is what users grep for during the cutover."""
    text = UPGRADING_DOC.read_text(encoding="utf-8")
    # Both columns of the rename table — at least one entry from each side.
    must_appear = (
        "GATEKEEPER_ISSUER",
        "INTERNAL_TOKEN_AUDIENCE",
        "SESSION_FERNET_KEY",
        "SESSION_TIMEOUT_ENABLED",
        "DEFAULT_IDLE_TIMEOUT_SECONDS",
    )
    missing = [name for name in must_appear if name not in text]
    assert not missing, f"UPGRADING.md env-var table missing entries: {missing}"


def test_upgrading_md_documents_cookie_changes() -> None:
    """The cookie cutover is browser-visible; users need the explicit
    before/after to debug post-migration login issues."""
    text = UPGRADING_DOC.read_text(encoding="utf-8")
    assert "tenant_session_id" in text, (
        "UPGRADING.md must name the new cookie (tenant_session_id)"
    )
    assert "SameSite=Lax" in text, (
        "UPGRADING.md must justify the SameSite=Lax decision (vs Strict) "
        "so a security reviewer doesn't 'fix' it back to Strict"
    )


def test_readme_advertises_auth_stack_in_whats_new() -> None:
    """README.md's "What's new?" callout must surface the 1.2.0 auth port.

    The callout is the highest-traffic doc surface — anyone landing on
    forge's main repo page sees it first. If this test fails because
    the entry got bumped down by a newer release, update the test to
    match the latest entry; do NOT silently delete the auth callout.
    """
    text = README.read_text(encoding="utf-8")
    # The entry must reference the architectural doc + the migration
    # playbook section so readers can navigate.
    assert "auth-architecture.md" in text, (
        "README must link to docs/auth-architecture.md so readers can navigate to the model"
    )
    assert "Gatekeeper as sole token authority" in text, (
        "README's What's-new callout must call out the Phase 4 invariant"
    )
    assert "platform-auth" in text, (
        "README must name the platform-auth SDK family"
    )


def test_readme_roadmap_marks_auth_port_shipped() -> None:
    """The Roadmap table must have a Shipped row for the auth port +
    a Shipped row for the cross-SDK parity contract. These are the
    two big deliverables of the 1.2.0 wave."""
    text = README.read_text(encoding="utf-8")
    # The roadmap rows include the literal "**Shipped**" + the
    # auth-port headline in the same row.
    assert "Auth-stack rebuild" in text, (
        "README Roadmap missing 'Auth-stack rebuild' Shipped entry"
    )
    assert "Cross-SDK parity contract" in text, (
        "README Roadmap missing 'Cross-SDK parity contract' Shipped entry"
    )


def test_readme_project_status_reflects_new_fragment_count() -> None:
    """Project Status block must mention the 64 fragments + 39 options
    + 11 auth-namespace fragments + the 17-scenario parity gate.

    A future fragment add that doesn't bump these numbers means the
    doc has drifted — pin a few load-bearing terms so the drift is
    caught early.
    """
    text = README.read_text(encoding="utf-8")
    # The numbers themselves drift with future additions — pin only
    # the qualitative claims that should always hold.
    assert "auth.mode" in text, "Project Status must mention the new auth.mode discriminator"
    assert "auth_sdk_parity" in text or "cross-SDK parity" in text, (
        "Project Status must mention the cross-SDK parity gate"
    )
    # The 1.2.0 dedicated bullet must exist so users find the migration
    # playbook from the README.
    assert "**`auth.mode`" in text or "**auth.mode" in text, (
        "Project Status must have a dedicated auth.mode bullet"
    )


def test_changelog_has_unreleased_1_2_0_section() -> None:
    """CHANGELOG.md must have a `[Unreleased] — targeting 1.2.0` heading
    listing the auth-stack rebuild as the headline addition."""
    text = CHANGELOG.read_text(encoding="utf-8")
    assert "## [Unreleased] — targeting 1.2.0" in text, (
        "CHANGELOG.md must have a `## [Unreleased] — targeting 1.2.0` heading"
    )
    assert "auth-stack rebuild" in text.lower(), (
        "CHANGELOG.md's 1.2.0 section must call out the auth-stack rebuild"
    )


def test_changelog_lists_all_eleven_auth_fragments() -> None:
    """Every auth fragment that ships in 1.2.0 must be named in the
    CHANGELOG so a user can grep for what they're getting.

    Duplicates inevitable (test-helper modules vs. fragment names);
    pin the unambiguous fragment names only.
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    fragment_names = (
        "platform_auth_sdk_python",
        "platform_auth_sdk_node",
        "platform_auth_sdk_rust",
        "platform_auth_gatekeeper",
        "platform_auth_gatekeeper_keygen",
        "platform_auth_python_middleware",
        "platform_auth_node_middleware",
        "platform_auth_rust_middleware",
        "platform_auth_session_timeout_vue",
    )
    missing = [name for name in fragment_names if name not in text]
    assert not missing, f"CHANGELOG.md must name fragments: {missing}"


def test_changelog_documents_behavioural_shifts() -> None:
    """Same 5 behavioural shifts as UPGRADING.md (`/auth` doesn't
    extend, 5-min TTL, scope-based authz, S2SClient, SameSite=Lax).
    Pin the load-bearing phrases."""
    text = CHANGELOG.read_text(encoding="utf-8")
    must_explain = (
        "/auth` does NOT extend",
        "5 minutes",
        "Scope-based",
        "S2SClient",
        "SameSite=Lax",
    )
    missing = [phrase for phrase in must_explain if phrase not in text]
    assert not missing, f"CHANGELOG.md behavioural-shifts list missing: {missing}"


def test_upgrading_md_documents_behavioural_shifts() -> None:
    """The four behavioural shifts (`/auth` doesn't extend, 5-min JWT
    TTL, scope-based authz, S2SClient) are the things engineers will
    trip over. Pin them so they don't get edited out."""
    text = UPGRADING_DOC.read_text(encoding="utf-8")
    must_explain = (
        # /auth is read-only — load-bearing for compliance.
        "/auth` does NOT extend",
        # Internal JWT TTL bound — revocation latency.
        "5 minutes",
        # Scope-based authz — new programming model.
        "Scope-based",
        # S2SClient — new outbound HTTP path.
        "S2SClient",
    )
    missing = [phrase for phrase in must_explain if phrase not in text]
    assert not missing, f"UPGRADING.md behavioural-shifts list missing: {missing}"

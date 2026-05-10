"""Cross-SDK parity contract for ``platform-auth`` (Phase 9).

The ``platform-auth`` SDK ships in three languages — Python
(``platform_auth``), Node (``@forge/platform-auth-node``), and Rust
(``platform-auth``). Cross-language parity is the load-bearing claim:
the same JWT input must yield the same ``IdentityContext`` (or the
same ``AuthError`` variant) across all three.

This package is the canonical scenario spec. Each language ships a
runner that consumes the spec and asserts its SDK matches. Runners
land in follow-up sub-phases (one per language); this package only
defines the spec + a meta-test that gates its internal coherence.

Cross-reference: implementation plan at
``~/.claude/plans/review-the-c-users-chifo-work-platform-a-pure-torvalds.md``
(Phase 9 deliverables).
"""

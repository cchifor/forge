"""Cross-language wildcard-scope parity for the platform-auth SDKs.

The authorization algorithm in :func:`scope_satisfies` must be identical
across the Python, Node, and Rust SDKs — a scope grant that authorizes a
request in one backend must authorize it in every backend, and (more
importantly) a grant that is *denied* in one must be denied in all.

The Python SDK is the reference. Its ``scope_satisfies`` is
**segment-bounded** for the verb wildcard: a held ``<prefix>:*`` grant
authorizes ``required`` iff ``required`` is *exactly* ``<prefix>:<one-
segment>`` — synthesized as ``":".join(parts[:-1]) + ":*"`` and compared
by exact set-membership. So ``workflow:*`` covers ``workflow:read`` but
NOT ``workflow:admin:retry``. It also has a **namespace wildcard**:
``*:<tail>`` (``":".join(parts[1:])`` prefixed with ``*:``) so ``*:read``
covers ``workflow:read``.

The Node (``scopes.ts``) and Rust (``scopes.rs``) ports historically
diverged on both points:

* They matched ``:*`` grants with an **unbounded** ``required.startsWith
  (prefix)`` / ``required.starts_with(prefix)`` — so ``workflow:*`` would
  wrongly authorize ``workflow:admin:retry`` (cross-segment widening), a
  privilege-escalation parity break versus Python.
* They had **no namespace-wildcard branch** at all — ``*:read`` would
  authorize nothing, so a token that works on Python silently 403s on
  Node/Rust.

These are pure-source assertions over the template files; behavioural
verification lives in ``tests/contract/auth_sdk_parity/``.
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments import FRAGMENT_REGISTRY


def _scopes_source(fragment_name: str, language: BackendLanguage, package: str, filename: str) -> str:
    frag = FRAGMENT_REGISTRY[fragment_name]
    impl = frag.implementations[language]
    path = Path(impl.fragment_dir) / "files" / "packages" / package / "src" / filename
    assert path.is_file(), f"scopes source missing: {path}"
    return path.read_text(encoding="utf-8")


def _node_source() -> str:
    return _scopes_source(
        "platform_auth_sdk_node", BackendLanguage.NODE, "platform-auth-node", "scopes.ts"
    )


def _rust_source() -> str:
    return _scopes_source(
        "platform_auth_sdk_rust", BackendLanguage.RUST, "platform-auth-rs", "scopes.rs"
    )


def _python_source() -> str:
    frag = FRAGMENT_REGISTRY["platform_auth_sdk_python"]
    impl = frag.implementations[BackendLanguage.PYTHON]
    path = (
        Path(impl.fragment_dir)
        / "files"
        / "packages"
        / "platform-auth"
        / "src"
        / "platform_auth"
        / "scopes.py"
    )
    assert path.is_file(), f"python scopes source missing: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Python reference — pins the two-branch, segment-bounded algorithm.
# ---------------------------------------------------------------------------


def test_python_reference_is_segment_bounded_with_namespace_wildcard() -> None:
    """The Python SDK is the reference: segment-bounded verb wildcard via a
    synthesized ``<prefix>:*`` string + exact membership, plus a
    ``*:<tail>`` namespace wildcard. Node and Rust must mirror this.
    """
    src = _python_source()
    # Segment-bounded verb wildcard: synthesize the candidate then membership-test.
    assert 'verb_wildcard = ":".join(parts[:-1]) + ":*"' in src, (
        "Python reference must synthesize the segment-bounded verb wildcard"
    )
    assert "verb_wildcard in held_set" in src
    # Namespace wildcard branch.
    assert 'namespace_wildcard = "*:" + ":".join(parts[1:])' in src, (
        "Python reference must synthesize the *:<tail> namespace wildcard"
    )
    assert "namespace_wildcard in held_set" in src
    # And it must NOT use an unbounded prefix match.
    assert "startswith" not in src.lower()


# ---------------------------------------------------------------------------
# Node parity.
# ---------------------------------------------------------------------------


def test_node_scopes_no_unbounded_prefix_match() -> None:
    """``scopes.ts`` must NOT authorize a ``:*`` grant by an unbounded
    ``required.startsWith(prefix)`` — that widens a verb wildcard across
    segments (``workflow:*`` wrongly covering ``workflow:admin:retry``),
    diverging from Python.
    """
    src = _node_source()
    assert "startsWith(prefix)" not in src, (
        "scopes.ts authorizes :* grants via unbounded required.startsWith(prefix); "
        "must be segment-bounded like Python (synthesize '<prefix>:*' + exact match)"
    )


def test_node_scopes_has_namespace_wildcard_branch() -> None:
    """``scopes.ts`` must have a ``*:<tail>`` namespace-wildcard branch so a
    held ``*:read`` authorizes ``workflow:read`` — same as Python.
    """
    src = _node_source()
    assert '"*:"' in src, (
        "scopes.ts has no namespace-wildcard branch; a held '*:read' must "
        "authorize 'workflow:read' to match Python"
    )


# ---------------------------------------------------------------------------
# Rust parity.
# ---------------------------------------------------------------------------


def test_rust_scopes_no_unbounded_prefix_match() -> None:
    """``scopes.rs`` must NOT authorize a ``:*`` grant by an unbounded
    ``required.starts_with(prefix)`` — same cross-segment widening defect
    as Node.
    """
    src = _rust_source()
    assert "starts_with(prefix)" not in src, (
        "scopes.rs authorizes :* grants via unbounded required.starts_with(prefix); "
        "must be segment-bounded like Python (synthesize '<prefix>:*' + exact match)"
    )


def test_rust_scopes_has_namespace_wildcard_branch() -> None:
    """``scopes.rs`` must have a ``*:<tail>`` namespace-wildcard branch so a
    held ``*:read`` authorizes ``workflow:read`` — same as Python.

    Rust synthesizes the candidate via ``format!("*:{}", ...)``; the
    ``*:`` prefix literal is the load-bearing signal.
    """
    src = _rust_source()
    assert '"*:{}"' in src, (
        "scopes.rs has no namespace-wildcard branch; a held '*:read' must "
        "authorize 'workflow:read' to match Python"
    )

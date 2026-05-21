"""Applier for source-snippet injections described by ``inject.yaml``.

Owns the largest and trickiest chunk of the pre-Epic-A ``_apply_fragment``
body: zone dispatch (``generated`` / ``user`` / ``merge``), sentinel
block detection, three-way merge integration, and per-suffix routing to
the LibCST Python injector, the TS regex/ts-morph injector, or the
text-marker fallback.

Epic A (1.1.0-alpha.1) introduced :class:`FragmentInjectionApplier`;
1.2.0-alpha.1 finalized the decomposition, deleting the legacy
``forge.feature_injector`` shim and inlining the body helpers
(``_apply_zoned_injection``, ``_apply_merge_zone``,
``_record_merge_baseline``, ``_load_merge_baseline``,
``_dispatch_injector``) into this module.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING

from forge.injectors.sentinels import (
    _has_sentinel_block,
    _inject_snippet,
    _read_block_body,
    _sentinel_tag,
)
from forge.sync.provenance import ProvenanceCollector

if TYPE_CHECKING:
    from forge.appliers.plan import FragmentPlan, _Injection
    from forge.fragment_context import FragmentContext


class FragmentInjectionApplier:
    """Applies every ``_Injection`` in the plan via the zoned dispatcher."""

    def apply(self, ctx: FragmentContext, plan: FragmentPlan) -> None:
        if not plan.injections:
            return
        for inj in plan.injections:
            target = ctx.backend_dir / inj.target
            applied = _apply_zoned_injection(
                target,
                inj,
                project_root=ctx.project_root,
                collector=ctx.provenance,
            )
            if applied and ctx.provenance is not None:
                # fragment_version is None today — Fragment has no version
                # field. TODO: thread fragment_version through FragmentPlan
                # once the fragment registry adopts semver per fragment.
                ctx.provenance.record(
                    target,
                    origin="fragment",
                    fragment_name=plan.feature_key,
                    fragment_version=None,
                )


def _apply_zoned_injection(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path | None = None,
    collector: ProvenanceCollector | None = None,
) -> bool:
    """Dispatch an injection according to its zone.

    Returns ``True`` when the injection was applied (the target file's
    content has changed), ``False`` when the zone semantics kept the
    existing content. Callers use the return value to decide whether to
    record a provenance update.

    Zone semantics (1.0.0a3+):
      * ``generated`` — always apply; replace any existing sentinel block.
      * ``user``      — apply only if no sentinel block for this tag
                        already exists. If a block is present, leave it
                        alone (the user may have customized its body).
      * ``merge``     — three-way merge against the provenance baseline
                        in ``forge.toml``'s ``[forge.merge_blocks]``
                        table. Emits ``.forge-merge`` sidecar on
                        conflict; leaves the target untouched. See
                        ``forge/merge.py``.
    """
    if inj.zone == "user" and _has_sentinel_block(target, inj.feature_key, inj.marker):
        return False

    if inj.zone == "merge" and project_root is not None:
        return _apply_merge_zone(target, inj, project_root=project_root, collector=collector)

    _dispatch_injector(target, inj)
    # Record the block baseline regardless of zone (Phase 6, bidirectional
    # sync). The forward applier's three-way-merge logic only reads
    # baselines for ``zone="merge"`` blocks, but the REVERSE direction
    # (``forge --harvest``) needs a per-block baseline for EVERY emitted
    # block so it can detect user edits. Recording baselines for
    # generated/user zones too is purely additive — no forward-path
    # behaviour changes.
    if collector is not None and project_root is not None:
        _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
    return True


def _apply_merge_zone(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path,
    collector: ProvenanceCollector | None,
) -> bool:
    """Three-way merge path for ``merge``-zone injections."""
    from forge.sync.merge import (  # noqa: PLC0415
        MergeBlockCollector,
        three_way_decide,
        write_sidecar,
    )

    try:
        rel_path = target.relative_to(project_root).as_posix()
    except ValueError:
        rel_path = target.as_posix()

    key = MergeBlockCollector.key_for(rel_path, inj.feature_key, inj.marker)
    baseline_sha = _load_merge_baseline(project_root, key)

    if not _has_sentinel_block(target, inj.feature_key, inj.marker):
        # First apply — no sentinel block yet. Behave like generated and
        # record the baseline.
        _dispatch_injector(target, inj)
        if collector is not None:
            _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
        return True

    current_body = _read_block_body(target, inj.feature_key, inj.marker) or ""
    new_body = inj.snippet

    decision = three_way_decide(
        baseline_sha=baseline_sha,
        current_body=current_body,
        new_body=new_body,
    )

    if decision in ("no-baseline", "applied"):
        _dispatch_injector(target, inj)
        if collector is not None:
            _record_merge_baseline(target, inj, project_root=project_root, collector=collector)
        return True

    if decision in ("skipped-no-change", "skipped-idempotent"):
        return False

    # decision == "conflict"
    tag = _sentinel_tag(inj.feature_key, inj.marker)
    write_sidecar(target, new_body, tag)
    return False


def _record_merge_baseline(
    target: Path,
    inj: _Injection,
    *,
    project_root: Path,
    collector: ProvenanceCollector,
) -> None:
    """Record the SHA of the block we just wrote — baseline for next compare."""
    from forge.sync.merge import sha256_of_text  # noqa: PLC0415

    body = _read_block_body(target, inj.feature_key, inj.marker)
    if body is None:
        return
    try:
        rel = target.relative_to(project_root).as_posix()
    except ValueError:
        rel = target.as_posix()
    # Trade-off note: ``inj.snippet`` is the POST-Jinja-render text.
    # ``_load_injections`` renders ``render: true`` snippets in place
    # before the ``_Injection`` is constructed; the pre-render template
    # source is no longer available at this call site. Harvest can still
    # detect fragment-template drift when the rendered snippet changes
    # (which happens whenever the underlying template OR an option value
    # the template reads changes). The blended signal is acceptable for
    # Phase 1 — Phase 4 harvest can recompute against the live fragment
    # at compare time.
    # TODO: preserve the raw pre-render snippet on _Injection (e.g.
    # snippet_raw: str | None) so this hash isolates template drift from
    # option-value drift.
    # TODO: thread fragment_version through _Injection once fragments
    # carry semver — today the field has no source.
    # line_range is None at the call site (the injection layer doesn't
    # surface the post-write line span). Harvest will recompute the
    # actual span from disk anyway.
    snippet_sha256 = hashlib.sha256(inj.snippet.encode("utf-8")).hexdigest()
    collector.record_merge_block(
        rel_posix_path=rel,
        feature_key=inj.feature_key,
        marker=inj.marker,
        block_sha=sha256_of_text(body),
        fragment_name=inj.feature_key,
        fragment_version=None,
        snippet_sha256=snippet_sha256,
        line_range=None,
    )


def _load_merge_baseline(project_root: Path, key: str) -> str | None:
    """Read a baseline sha from ``forge.toml`` if present.

    Initiative #6 (caching): reads go through
    :func:`forge.sync._manifest_cache.cached_read_forge_toml`, which
    parses each unique manifest path exactly once per
    :func:`manifest_cache_scope` activation. The CLI entry points
    for ``forge --update`` and ``forge --harvest`` open that scope
    once per invocation, so a fragment with N merge blocks now pays
    one tomlkit parse instead of N. Outside an active scope the
    shim falls through to a direct read, preserving the legacy
    contract for tests and one-off callers.
    """
    manifest = project_root / "forge.toml"
    if not manifest.is_file():
        return None
    try:
        from forge.sync._manifest_cache import cached_read_forge_toml  # noqa: PLC0415

        data = cached_read_forge_toml(manifest)
    except Exception:  # noqa: BLE001
        return None
    entry = data.merge_blocks.get(key)
    if not entry:
        return None
    sha = entry.get("sha256")
    return str(sha) if sha else None


def _dispatch_injector(target: Path, inj: _Injection) -> None:
    """Route an injection to the right backend based on the target's extension.

    Python (``.py``) goes through the LibCST-backed injector; TypeScript /
    JavaScript (``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` / ``.mjs``) through
    the regex-based TS injector. Everything else (``.rs``, ``.toml``,
    ``.yaml``) falls back to the legacy text-marker injector.
    """
    suffix = target.suffix.lower()
    if suffix in (".py", ".pyi"):
        from forge.injectors.python_ast import inject_python  # noqa: PLC0415

        inject_python(target, inj.feature_key, inj.marker, inj.snippet, inj.position)
        return
    if suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
        from forge.injectors.ts_ast import inject_ts  # noqa: PLC0415

        inject_ts(target, inj.feature_key, inj.marker, inj.snippet, inj.position)
        return
    _inject_snippet(target, inj.feature_key, inj.marker, inj.snippet, inj.position)

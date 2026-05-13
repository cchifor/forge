"""Behavioural tests for the ``migrate-provenance-v2`` codemod.

The codemod upgrades pre-1.2 ``forge.toml`` manifests to schema v2 in
place — see :mod:`forge.migrations.migrate_provenance_v2` for the full
algorithm. These tests build synthetic v1 manifests in a tmpdir, run
the codemod, and assert the enrichments landed:

* ``schema_version = 2`` stamped.
* ``[forge.template_versions]`` populated.
* ``fragment_version`` filled in for fragment-origin provenance + merge
  block entries whose fragment is known to ``FRAGMENT_REGISTRY``.
* ``fragment_name`` derived from each merge_block key.
* BEGIN sentinels in injected files get ``fp:<hex8>`` trailers.
* Unknown fragments → warning, no crash, version absent.
* Dry-run leaves disk untouched.
* Idempotency: second pass on a v2 manifest is a no-op.
"""

from __future__ import annotations

import logging
from pathlib import Path

import tomlkit

import forge
from forge.injectors.sentinels import _block_fingerprint
from forge.migrations.base import discover_migrations
from forge.migrations.migrate_provenance_v2 import (
    DESCRIPTION,
    FROM,
    NAME,
    TO,
    run,
)

# ---------------------------------------------------------------- registration


def test_codemod_registered_in_discover() -> None:
    """The codemod is reachable via ``forge --migrate <NAME>``."""
    migrations = {m.name: m for m in discover_migrations()}
    assert NAME in migrations, f"codemod {NAME!r} not in discover_migrations() — CLI can't reach it"
    entry = migrations[NAME]
    assert entry.from_version == FROM
    assert entry.to_version == TO
    assert entry.description == DESCRIPTION


def test_codemod_runs_after_adopt_baseline() -> None:
    """Order matters: provenance-v2 enrichment must run AFTER adopt-baseline."""
    order = [m.name for m in discover_migrations()]
    assert "adopt-baseline" in order
    assert NAME in order
    assert order.index(NAME) > order.index("adopt-baseline")


# ---------------------------------------------------------------- helpers


def _write_v1_manifest(
    root: Path,
    *,
    provenance: dict[str, dict[str, str]] | None = None,
    merge_blocks: dict[str, dict[str, str]] | None = None,
    templates: dict[str, str] | None = None,
) -> Path:
    """Write a v1-shape ``forge.toml`` at ``root``.

    v1 shape: no ``schema_version``, no ``[forge.template_versions]``,
    sparse per-entry sub-tables.
    """
    doc = tomlkit.document()
    forge_tbl = tomlkit.table()
    forge_tbl.add("version", "1.1.5")
    forge_tbl.add("project_name", "demo")
    if templates:
        tpl = tomlkit.table()
        for k, v in templates.items():
            tpl.add(k, v)
        forge_tbl.add("templates", tpl)
    if provenance:
        prov = tomlkit.table()
        for path, entry in provenance.items():
            sub = tomlkit.table()
            for ek, ev in entry.items():
                sub.add(ek, ev)
            prov.add(path, sub)
        forge_tbl.add("provenance", prov)
    if merge_blocks:
        mb = tomlkit.table()
        for key, entry in merge_blocks.items():
            sub = tomlkit.table()
            for ek, ev in entry.items():
                sub.add(ek, ev)
            mb.add(key, sub)
        forge_tbl.add("merge_blocks", mb)
    doc.add("forge", forge_tbl)
    path = root / "forge.toml"
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return path


def _make_v1_injected_file(
    path: Path,
    feature_key: str,
    marker_name: str,
    body: str,
    *,
    comment_prefix: str = "#",
) -> str:
    """Drop a file with a v1-shape BEGIN/END sentinel pair (no fp: trailer).

    Returns the in-file body string (used by tests asserting the fingerprint).
    """
    tag = f"{feature_key}:{marker_name}"
    contents = (
        f"{comment_prefix} module header\n"
        f"{comment_prefix} FORGE:{marker_name}\n"
        f"{comment_prefix} FORGE:BEGIN {tag}\n"
        f"{body}\n"
        f"{comment_prefix} FORGE:END {tag}\n"
        f"{comment_prefix} module footer\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return body


# ---------------------------------------------------------------- happy path


def test_v1_to_v2_happy_path(tmp_path: Path) -> None:
    """Full v1 → v2 enrichment lands on disk."""
    # A real built-in fragment name so the registry lookup succeeds.
    fragment_name = "correlation_id"
    feature_key = fragment_name
    marker_name = "MIDDLEWARE_REGISTRATION"

    target_rel = "services/python-svc/app/main.py"
    target = tmp_path / target_rel
    body = "app.add_middleware(CorrelationIdMiddleware)"
    _make_v1_injected_file(target, feature_key, marker_name, body)

    merge_key = f"{target_rel}::{feature_key}:{marker_name}"
    _write_v1_manifest(
        tmp_path,
        provenance={
            target_rel: {
                "origin": "fragment",
                "sha256": "deadbeef",
                "fragment_name": fragment_name,
            },
        },
        merge_blocks={
            merge_key: {"sha256": "cafef00d"},
        },
        templates={"python": "services/python-service-template"},
    )

    report = run(tmp_path, dry_run=False, quiet=True)

    assert report.applied is True
    assert report.skipped_reason is None
    # Summary line should record at least one resolution + sentinel write.
    summary = report.changes[0]
    assert "sentinels_fingerprinted: 1" in summary
    assert "fragment_versions_resolved: 2" in summary  # one prov + one mb

    # On-disk forge.toml is v2-shaped.
    doc = tomlkit.parse((tmp_path / "forge.toml").read_text(encoding="utf-8"))
    forge_tbl = doc["forge"]
    assert int(forge_tbl["schema_version"]) == 2
    assert "template_versions" in forge_tbl
    assert str(forge_tbl["template_versions"]["python"]) == forge.__version__

    prov_entry = forge_tbl["provenance"][target_rel]
    assert str(prov_entry["fragment_version"]) == forge.__version__
    assert str(prov_entry["fragment_name"]) == fragment_name

    mb_entry = forge_tbl["merge_blocks"][merge_key]
    assert str(mb_entry["fragment_name"]) == fragment_name
    assert str(mb_entry["fragment_version"]) == forge.__version__
    # Baseline sha256 must be preserved — never recomputed.
    assert str(mb_entry["sha256"]) == "cafef00d"

    # In-file BEGIN sentinel carries the fingerprint now.
    updated_target = target.read_text(encoding="utf-8")
    expected_fp = _block_fingerprint(body)
    assert f"FORGE:BEGIN {feature_key}:{marker_name} fp:{expected_fp}" in updated_target
    # END sentinel is left untouched (no fp on END lines).
    assert f"FORGE:END {feature_key}:{marker_name}\n" in updated_target


# ---------------------------------------------------------------- idempotency


def test_second_pass_is_noop_on_v2(tmp_path: Path) -> None:
    """Running on a v2 manifest is a no-op."""
    # Write a minimal v2 manifest directly.
    doc = tomlkit.document()
    forge_tbl = tomlkit.table()
    forge_tbl.add("schema_version", 2)
    forge_tbl.add("version", "1.2.0")
    forge_tbl.add("project_name", "demo")
    doc.add("forge", forge_tbl)
    (tmp_path / "forge.toml").write_text(tomlkit.dumps(doc), encoding="utf-8")

    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied is False
    assert report.skipped_reason is not None
    assert "v2" in report.skipped_reason


def test_re_run_after_apply_is_noop(tmp_path: Path) -> None:
    """v1 → v2 then re-run leaves the second pass with nothing to do."""
    target = tmp_path / "services/x/main.py"
    _make_v1_injected_file(target, "correlation_id", "MARKER_A", "snippet")
    _write_v1_manifest(
        tmp_path,
        merge_blocks={
            "services/x/main.py::correlation_id:MARKER_A": {"sha256": "abc"},
        },
    )
    first = run(tmp_path, dry_run=False, quiet=True)
    assert first.applied is True

    second = run(tmp_path, dry_run=False, quiet=True)
    assert second.applied is False
    assert "v2" in (second.skipped_reason or "")


# ---------------------------------------------------------------- dry-run


def test_dry_run_does_not_mutate(tmp_path: Path) -> None:
    """Dry-run computes changes but leaves disk untouched."""
    target_rel = "services/x/main.py"
    target = tmp_path / target_rel
    _make_v1_injected_file(target, "correlation_id", "M", "body")
    manifest_path = _write_v1_manifest(
        tmp_path,
        merge_blocks={f"{target_rel}::correlation_id:M": {"sha256": "abc"}},
    )

    manifest_before = manifest_path.read_text(encoding="utf-8")
    target_before = target.read_text(encoding="utf-8")

    report = run(tmp_path, dry_run=True, quiet=True)

    assert report.applied is False  # dry-run never reports applied
    # Changes ARE recorded so the user can preview the diff.
    assert any("fp:" in c for c in report.changes)
    assert any("schema_version" in c for c in report.changes)
    # Disk is unchanged.
    assert manifest_path.read_text(encoding="utf-8") == manifest_before
    assert target.read_text(encoding="utf-8") == target_before


# ---------------------------------------------------------------- unknown frags


def test_unknown_fragment_warns_no_crash(tmp_path: Path, caplog: object) -> None:
    """A fragment in the manifest that isn't in FRAGMENT_REGISTRY is
    logged but doesn't crash; its version stays absent."""
    target_rel = "services/x/main.py"
    target = tmp_path / target_rel
    _make_v1_injected_file(target, "ghost_fragment_xyz", "MARKER", "body")
    _write_v1_manifest(
        tmp_path,
        provenance={
            target_rel: {
                "origin": "fragment",
                "sha256": "abc",
                "fragment_name": "ghost_fragment_xyz",
            },
        },
        merge_blocks={
            f"{target_rel}::ghost_fragment_xyz:MARKER": {"sha256": "def"},
        },
    )

    # caplog is a pytest fixture — type-stripped to avoid pytest dep at
    # module-import time.
    import _pytest.logging  # noqa: PLC0415

    assert isinstance(caplog, _pytest.logging.LogCaptureFixture)
    with caplog.at_level(logging.WARNING, logger="forge.migrations.migrate_provenance_v2"):
        report = run(tmp_path, dry_run=False, quiet=True)

    assert report.applied is True
    # Warning fired.
    assert any("ghost_fragment_xyz" in rec.message for rec in caplog.records)

    # fragment_version absent on both.
    doc = tomlkit.parse((tmp_path / "forge.toml").read_text(encoding="utf-8"))
    prov_entry = doc["forge"]["provenance"][target_rel]
    assert "fragment_version" not in prov_entry

    mb_entry = doc["forge"]["merge_blocks"][f"{target_rel}::ghost_fragment_xyz:MARKER"]
    assert "fragment_version" not in mb_entry
    # fragment_name IS derived from the key — that's keyless of the
    # registry, so it lands even for unknown fragments.
    assert str(mb_entry["fragment_name"]) == "ghost_fragment_xyz"


# ---------------------------------------------------------------- sentinel


def test_sentinel_fingerprint_added_in_place(tmp_path: Path) -> None:
    """BEGIN line gets ` fp:<8hex>` appended; END line is left alone."""
    target_rel = "services/x/handler.py"
    target = tmp_path / target_rel
    body = "do_thing()"
    _make_v1_injected_file(target, "correlation_id", "MARKER_B", body)
    _write_v1_manifest(
        tmp_path,
        merge_blocks={f"{target_rel}::correlation_id:MARKER_B": {"sha256": "x"}},
    )

    run(tmp_path, dry_run=False, quiet=True)

    text = target.read_text(encoding="utf-8")
    expected_fp = _block_fingerprint(body)
    # Exactly one BEGIN with fp:; END unchanged.
    begin_lines = [ln for ln in text.splitlines() if "FORGE:BEGIN correlation_id:MARKER_B" in ln]
    assert len(begin_lines) == 1
    assert begin_lines[0].rstrip().endswith(f"fp:{expected_fp}")
    end_lines = [ln for ln in text.splitlines() if "FORGE:END correlation_id:MARKER_B" in ln]
    assert len(end_lines) == 1
    # The END line MUST NOT carry an fp: trailer (v2 grammar matches v1
    # on END to keep legacy parsers working).
    assert "fp:" not in end_lines[0]


def test_sentinel_already_fingerprinted_skipped(tmp_path: Path) -> None:
    """A BEGIN line that already has ``fp:<hex>`` is left alone."""
    target_rel = "services/x/m.py"
    target = tmp_path / target_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# FORGE:MARKER_C\n"
        "# FORGE:BEGIN correlation_id:MARKER_C fp:deadbeef\n"
        "snippet\n"
        "# FORGE:END correlation_id:MARKER_C\n",
        encoding="utf-8",
    )
    _write_v1_manifest(
        tmp_path,
        merge_blocks={f"{target_rel}::correlation_id:MARKER_C": {"sha256": "x"}},
    )

    before = target.read_text(encoding="utf-8")
    report = run(tmp_path, dry_run=False, quiet=True)
    after = target.read_text(encoding="utf-8")

    assert report.applied is True
    assert before == after, "BEGIN line with existing fp: must not be rewritten"


# ---------------------------------------------------------------- degenerate


def test_missing_forge_toml_is_skip(tmp_path: Path) -> None:
    """No ``forge.toml`` → skip with reason, never crash."""
    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied is False
    assert "No forge.toml" in (report.skipped_reason or "")


def test_missing_target_file_is_recorded_as_error(tmp_path: Path) -> None:
    """Merge-block target file no longer exists → error recorded; manifest
    still upgraded."""
    _write_v1_manifest(
        tmp_path,
        merge_blocks={"missing/path.py::correlation_id:M": {"sha256": "x"}},
    )

    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied is True
    assert any("missing/path.py" in c for c in report.changes)
    # Schema version still bumped.
    doc = tomlkit.parse((tmp_path / "forge.toml").read_text(encoding="utf-8"))
    assert int(doc["forge"]["schema_version"]) == 2


def test_unparseable_merge_block_key_recorded(tmp_path: Path) -> None:
    """A merge_blocks key that doesn't match the canonical shape is
    reported as an error but doesn't abort the migration."""
    _write_v1_manifest(
        tmp_path,
        merge_blocks={"hand-edited-junk-key": {"sha256": "x"}},
    )

    report = run(tmp_path, dry_run=False, quiet=True)
    assert report.applied is True
    assert any("unparseable" in c for c in report.changes)

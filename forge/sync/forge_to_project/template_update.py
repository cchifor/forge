"""Wrap :func:`copier.run_update` so ``forge --update`` re-renders base templates.

Phase 5 of the bidirectional-sync plan. Pre-1.2 ``forge --update``
re-applied fragments only and left base-template re-renders to a
manual ``cd backend && copier update``. With per-template semver
stamped into ``forge.toml`` (see :mod:`forge.sync.template_version`),
the updater can detect a version delta and call Copier itself.

Algorithm:

  1. For each backend/frontend in the project, look up the version
     recorded in ``forge.toml`` and compare to the live template's
     resolved version. A delta → :class:`TemplateUpdateTask` enqueued
     for that subtree.
  2. Before Copier runs: surface files whose provenance says
     ``base-template`` + classification is ``user-modified`` as
     ``.forge-merge`` sidecars. The user's edits are preserved verbatim
     and the would-be-rendered content lands next to them; ``forge
     --resolve`` can walk these the same as fragment-level sidecars.
  3. Invoke :func:`copier.run_update` with ``conflict="rej"`` so any
     three-way conflict Copier itself spots emits a ``.rej`` file.
  4. Post-process: convert each ``.rej`` Copier left behind into a
     forge ``.forge-merge`` sidecar — single sidecar format, one
     downstream tool (``forge --resolve``) for everything.

Out of scope:

* Three-way merge of Jinja-rendered files by hand. Copier already
  does the substantive merge work; we just adapt its output shape.
* Multi-template branching when one project mixes plugin and built-in
  templates — :class:`TemplateUpdateTask` carries a ``language`` field
  but the caller threads the registry lookup, so each task is
  self-describing.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import copier
import copier.errors

from forge.sync.merge import sha256_of_file

# Outcomes :func:`run_template_update` can return — narrow the literal
# set so callers can switch-by-string without freelancing.
TemplateUpdateStatus = Literal["applied", "skipped", "conflict", "error"]


@dataclass(frozen=True)
class TemplateUpdateTask:
    """One pending Copier re-render against a backend or frontend subtree.

    ``language`` is the canonical wire value (``"python"``, ``"vue"``)
    used in :attr:`ForgeTomlData.template_versions`. ``target_dir`` is
    the on-disk directory Copier will operate against; ``template_src``
    is the local path to the template root (``copier.yml``-bearing
    directory). The version fields are kept for diagnostics — the
    actual delta detection happens upstream in the updater.

    ``base_template_src`` is set for *two-stage* (overlay) layouts: the
    shared base template the generator renders *before* the
    ``template_src`` overlay. The project's ``.copier-answers.yml``
    records only the overlay ``_src_path``, so a plain
    ``copier.run_update(dst_path=...)`` re-renders the overlay alone and
    silently skips the base. When this field is set,
    :func:`run_template_update` re-renders the base first, then the
    overlay. ``None`` ⇒ a self-contained single-render template (the
    overlay's answers cover the whole subtree).
    """

    language: str
    project_version: str
    current_version: str
    target_dir: Path
    template_src: Path
    base_template_src: Path | None = None


@dataclass(frozen=True)
class TemplateUpdateOutcome:
    """Result of one :func:`run_template_update` call.

    * ``applied`` — Copier ran and produced changes (or was a no-op on
      a clean re-render). No ``.rej`` files emitted.
    * ``conflict`` — Copier emitted at least one ``.rej`` file that we
      converted into a ``.forge-merge`` sidecar. Caller should surface
      to the user; subsequent ``forge --resolve`` handles them.
    * ``skipped`` — caller-controlled skip (e.g. ``no_template_update``
      flag). No Copier invocation.
    * ``error`` — Copier raised; ``error_message`` carries the
      exception text. Caller decides whether to abort the wider update
      run (current policy: yes, fragments don't re-apply after a
      template update failure).
    """

    task: TemplateUpdateTask
    status: TemplateUpdateStatus
    rej_files: tuple[Path, ...] = ()
    sidecar_files: tuple[Path, ...] = ()
    error_message: str | None = None
    presurfaced_sidecars: tuple[Path, ...] = ()


def _presurface_user_modified_sidecars(
    target_dir: Path,
    base_template_paths: tuple[str, ...],
    project_root: Path,
) -> tuple[Path, ...]:
    """Emit ``.forge-merge`` sidecars for user-modified base-template files.

    Pre-flight before Copier runs. For each path the manifest tags
    ``origin=base-template`` whose current on-disk SHA differs from its
    recorded baseline (i.e. classification is ``user-modified``), copy
    the existing on-disk body to a ``<path>.forge-merge`` sidecar so the
    user has a record of their edits even if Copier later overwrites or
    conflicts the file.

    ``base_template_paths`` is the POSIX-rel paths under ``project_root``
    that the caller already classified as base-template + user-modified.
    We only emit sidecars for paths that fall under ``target_dir`` (the
    Copier subtree) — paths outside it aren't touched by this Copier
    call so they don't need pre-flight handling.

    Returns the list of sidecar paths actually written. Errors during
    sidecar write are swallowed individually (the missing sidecar means
    the user loses an edit-trail file, but it shouldn't abort the
    template update — fragments still need to re-apply on top).
    """
    out: list[Path] = []
    try:
        target_resolved = target_dir.resolve()
    except OSError:
        return ()
    for rel in base_template_paths:
        on_disk = project_root / rel
        if not on_disk.is_file():
            continue
        try:
            if not on_disk.resolve().is_relative_to(target_resolved):
                continue
        except OSError:
            continue
        try:
            body = on_disk.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            # Binary file or unreadable — skip the text-mode pre-surface;
            # Copier itself will produce the .rej variant if there's a
            # conflict.
            continue
        sidecar = on_disk.with_suffix(on_disk.suffix + ".forge-merge")
        if sidecar.exists():
            # Don't clobber an existing sidecar from a prior run — the
            # user may have material in there they haven't resolved yet.
            continue
        header = (
            "# forge merge pre-surface — base-template re-render\n"
            f"# target: {on_disk.name}\n"
            "# \n"
            "# Your edits to this base-template file are preserved here\n"
            "# before forge invokes Copier to re-render the template at\n"
            "# its new version. Copier may overwrite the target or emit a\n"
            "# .rej file; this sidecar records the pre-update state so you\n"
            "# can recover your edits if needed.\n"
            "\n"
            f"{body}"
        )
        try:
            sidecar.write_text(header, encoding="utf-8")
        except OSError:
            continue
        out.append(sidecar)
    return tuple(out)


def _rej_to_sidecar(rej_path: Path) -> Path | None:
    """Convert a Copier ``.rej`` file into a forge ``.forge-merge`` sidecar.

    Copier emits ``<target>.rej`` with the body of the would-be rendered
    file when ``conflict="rej"`` is set and a three-way merge could not
    be resolved. Forge ships a single sidecar shape across its merge
    machinery (``.forge-merge`` / ``.forge-merge.bin``); this routine
    rewrites the file under that name with a forge-style header so
    ``forge --resolve`` and the downstream resolution flows see one
    consistent format.

    Returns the path of the sidecar written, or ``None`` if the source
    ``.rej`` was unreadable or the destination already existed (so we
    leave both for manual review rather than clobbering one).
    """
    target = rej_path.with_suffix("")
    # ``.rej`` is appended to whatever suffix the original had (e.g.
    # ``main.py.rej``). ``with_suffix("")`` strips just the ``.rej`` so
    # ``target`` is ``main.py``.
    if rej_path.suffix != ".rej":
        return None
    try:
        body = rej_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        # Binary diff or unreadable — leave the .rej for the user.
        return None
    sidecar = target.with_suffix(target.suffix + ".forge-merge")
    if sidecar.exists():
        # Pre-flight already wrote a sidecar (the user-modified case).
        # The Copier-emitted .rej body is the would-be-rendered content;
        # append it after a banner so the resolver sees both pieces.
        try:
            existing = sidecar.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        separator = (
            "\n"
            "# ----------------------------------------------------------\n"
            "# Copier-emitted .rej content follows — this is what the new\n"
            "# template version wanted to write. Compare with the body\n"
            "# above (your pre-update file content) and the current\n"
            "# on-disk target to decide.\n"
            "# ----------------------------------------------------------\n"
            "\n"
        )
        try:
            sidecar.write_text(existing + separator + body, encoding="utf-8")
        except OSError:
            return None
    else:
        header = (
            "# forge merge conflict — base-template re-render\n"
            f"# target: {target.name}\n"
            "# \n"
            "# Copier could not auto-merge the new template version into\n"
            "# your file. The content below is what the new template\n"
            "# would emit. Merge by hand, then delete this sidecar.\n"
            "\n"
        )
        try:
            sidecar.write_text(header + body, encoding="utf-8")
        except OSError:
            return None
    # Remove the .rej now that we've consumed it.
    with contextlib.suppress(OSError):
        rej_path.unlink(missing_ok=True)
    return sidecar


def _collect_rej_files(target_dir: Path) -> tuple[Path, ...]:
    """Walk ``target_dir`` for ``.rej`` files Copier emitted."""
    if not target_dir.is_dir():
        return ()
    out: list[Path] = []
    for p in target_dir.rglob("*.rej"):
        if p.is_file():
            out.append(p)
    return tuple(sorted(out))


# Answers-file name used for the transient base-template re-render of a
# two-stage layout. Copier resolves the template ``_src_path`` from the
# answers file under ``dst_path``; this one points at the shared base so
# ``run_update`` re-renders it before the overlay's default answers file
# re-renders the overlay on top. Removed after the base render completes.
_BASE_ANSWERS_RELPATH = ".copier-answers.base.yml"


def _write_base_answers_file(target_dir: Path, base_src: Path) -> Path | None:
    """Stamp a transient base-template answers file under ``target_dir``.

    Two-stage layouts record only the overlay ``_src_path`` in their
    ``.copier-answers.yml``. To re-render the shared base on update we
    need an answers file whose ``_src_path`` points at the base while
    preserving the user's recorded answers. Clone the existing answers
    file, swap ``_src_path`` (and drop the now-stale ``_commit`` so
    Copier re-resolves the base's ref), and write it next to the
    overlay's. Returns the path written, or ``None`` if the source
    answers file is missing/unreadable (nothing to re-render against).
    """
    import yaml

    src_answers = target_dir / ".copier-answers.yml"
    if not src_answers.is_file():
        return None
    try:
        data = yaml.safe_load(src_answers.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(data, dict):
        return None
    data = dict(data)
    data["_src_path"] = str(base_src)
    # ``_commit`` pinned the overlay's ref; it's meaningless for the base.
    data.pop("_commit", None)
    out = target_dir / _BASE_ANSWERS_RELPATH
    try:
        out.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    except OSError:
        return None
    return out


def _cleanup_base_answers_file(target_dir: Path, relpath: str | None) -> None:
    """Remove the transient base-template answers file, if one was written.

    The base re-render uses a scratch ``.copier-answers.base.yml`` whose
    only purpose is to point Copier at the shared base. It must never
    persist in the generated project — the overlay's
    ``.copier-answers.yml`` remains the single recorded answers file.
    """
    if not relpath:
        return
    with contextlib.suppress(OSError):
        (target_dir / relpath).unlink(missing_ok=True)


def run_template_update(
    task: TemplateUpdateTask,
    *,
    quiet: bool = False,
    base_template_paths: tuple[str, ...] = (),
    project_root: Path | None = None,
) -> TemplateUpdateOutcome:
    """Run ``copier.run_update`` against one backend / frontend subtree.

    ``base_template_paths`` is the POSIX-rel manifest paths classified
    as ``base-template`` + ``user-modified`` at the start of the update
    run; the pre-flight emits sidecars for any that fall under
    ``task.target_dir`` so the user's edits are recoverable even if
    Copier overwrites them.

    ``project_root`` anchors the rel-path resolution for the pre-flight
    pass. Defaults to ``task.target_dir.parent.parent`` (the
    ``<project>/services/<backend>/`` -> ``<project>`` walk), which is
    correct for the conventional layout the rest of forge enforces.
    """
    if project_root is None:
        project_root = task.target_dir.parent.parent

    presurfaced = _presurface_user_modified_sidecars(
        task.target_dir,
        base_template_paths,
        project_root,
    )

    # ``conflict="rej"`` puts conflict markers in a side file rather
    # than inline — easier for forge to post-process into its own
    # sidecar shape. ``defaults=True`` + ``skip_answered=True`` keeps
    # the call non-interactive against the project's
    # ``.copier-answers.yml`` (forge wrote it at generate time).
    #
    # Two-stage (overlay) layouts: the project's ``.copier-answers.yml``
    # records only the overlay ``_src_path``, so a plain ``run_update``
    # re-renders the overlay alone and skips the shared base. Re-render
    # the base FIRST (via a transient answers file pointing at it), then
    # let the overlay re-apply on top — mirroring the generator's render
    # order so base-template changes are not silently dropped.
    base_answers_relpath: str | None = None
    if task.base_template_src is not None:
        base_answers = _write_base_answers_file(task.target_dir, task.base_template_src)
        if base_answers is not None:
            base_answers_relpath = base_answers.name
    try:
        if base_answers_relpath is not None:
            copier.run_update(
                dst_path=str(task.target_dir),
                answers_file=base_answers_relpath,
                defaults=True,
                overwrite=False,
                skip_answered=True,
                unsafe=True,
                quiet=quiet,
                conflict="rej",
            )
        copier.run_update(
            dst_path=str(task.target_dir),
            defaults=True,
            overwrite=False,
            skip_answered=True,
            unsafe=True,
            quiet=quiet,
            conflict="rej",
        )
    except copier.errors.CopierError as exc:
        _cleanup_base_answers_file(task.target_dir, base_answers_relpath)
        return TemplateUpdateOutcome(
            task=task,
            status="error",
            error_message=f"{type(exc).__name__}: {exc}",
            presurfaced_sidecars=presurfaced,
        )
    except OSError as exc:
        _cleanup_base_answers_file(task.target_dir, base_answers_relpath)
        return TemplateUpdateOutcome(
            task=task,
            status="error",
            error_message=f"OSError: {exc}",
            presurfaced_sidecars=presurfaced,
        )
    _cleanup_base_answers_file(task.target_dir, base_answers_relpath)

    rej_files = _collect_rej_files(task.target_dir)
    sidecars: list[Path] = []
    for rej in rej_files:
        side = _rej_to_sidecar(rej)
        if side is not None:
            sidecars.append(side)

    status: TemplateUpdateStatus = "conflict" if rej_files else "applied"
    return TemplateUpdateOutcome(
        task=task,
        status=status,
        rej_files=rej_files,
        sidecar_files=tuple(sidecars),
        presurfaced_sidecars=presurfaced,
    )


def restamp_base_template_provenance(
    project_root: Path,
    *,
    provenance: dict[str, dict[str, object]],
    language: str,
    target_dir: Path,
    new_version: str,
) -> int:
    """Update per-file provenance after a successful Copier re-render.

    Walks ``provenance`` for entries whose ``origin`` is
    ``base-template`` and whose path falls under ``target_dir``. For
    each, recomputes the SHA from on-disk content and stamps the new
    ``template_version``. Returns the number of entries mutated so the
    caller can surface it in the update summary.

    ``language`` is the wire value (``"python"`` / ``"vue"`` / ...);
    today we don't filter by language on the entries themselves
    (provenance ``template_name`` is the template path string, not a
    language), but the parameter is kept on the signature so future
    changes that need it don't require a re-wire.
    """
    _ = language  # reserved for future per-language scoping
    try:
        target_resolved = target_dir.resolve()
    except OSError:
        return 0
    mutated = 0
    for rel, entry in list(provenance.items()):
        if entry.get("origin") != "base-template":
            continue
        on_disk = project_root / rel
        if not on_disk.is_file():
            continue
        try:
            if not on_disk.resolve().is_relative_to(target_resolved):
                continue
        except OSError:
            continue
        new_sha = sha256_of_file(on_disk)
        new_entry = dict(entry)
        # Only mutate when something actually changed — keeps idempotent
        # re-runs from churning the manifest.
        changed = False
        if str(new_entry.get("sha256", "")) != new_sha:
            new_entry["sha256"] = new_sha
            changed = True
        if str(new_entry.get("template_version", "")) != new_version:
            new_entry["template_version"] = new_version
            changed = True
        if changed:
            provenance[rel] = new_entry
            mutated += 1
    return mutated


__all__ = [
    "TemplateUpdateOutcome",
    "TemplateUpdateStatus",
    "TemplateUpdateTask",
    "restamp_base_template_provenance",
    "run_template_update",
]

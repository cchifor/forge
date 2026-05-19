"""Copier orchestration -- generates all project components."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

# Windows consoles default to cp1252 and raise UnicodeEncodeError on emoji /
# non-Latin chars that lint tools sometimes emit. Reconfigure once so every
# later ``print`` survives mixed-locale output.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ty:ignore[unresolved-attribute]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # ty:ignore[unresolved-attribute]
    except (AttributeError, OSError):
        pass

from copier import run_copy
from copier.errors import CopierError

from forge import variable_mapper
from forge.capability_resolver import ResolvedPlan, resolve
from forge.config import (
    BACKEND_REGISTRY,
    BackendConfig,
    BackendLanguage,
    FrontendFramework,
    ProjectConfig,
    frontend_uses_subdirectory,
)
from forge.docker_manager import (
    render_compose,
    render_frontend_dockerfile,
    render_init_db,
    render_keycloak_realm,
    render_nginx_conf,
    render_workspace_cargo_toml,
    render_workspace_package_json,
)
from forge.errors import (
    FILESYSTEM_IO_ERROR,
    TEMPLATE_JINJA_ERROR,
    TEMPLATE_NOT_FOUND,
    TEMPLATE_RENDER_FAILED,
    FilesystemError,
    ForgeError,
    GeneratorError,
    TemplateError,
)
from forge.logging import get_logger, phase_timer
from forge.sync.forge_to_project import apply_features, apply_project_features
from forge.sync.provenance import ProvenanceCollector

_logger = get_logger("generator")

__all__ = ["GeneratorError", "generate"]

TEMPLATES_DIR = Path(__file__).parent / "templates"

TEMPLATE_DIRS = {
    "backend": "services/python-service-template",
    "e2e": "tests/e2e-testing-template",
    FrontendFramework.VUE: "apps/vue-frontend-template",
    FrontendFramework.SVELTE: "apps/svelte-frontend-template",
    FrontendFramework.FLUTTER: "apps/flutter-frontend-template",
}


def generate(config: ProjectConfig, quiet: bool = False, dry_run: bool = False) -> Path:
    """Generate all project components and return the project root path.

    When ``dry_run=True``, generation runs into a fresh temporary directory
    (never touching ``config.output_dir``) and the temp path is returned
    for inspection. The caller is responsible for cleanup.
    """
    project_root = _create_root(config, dry_run)
    collector = _setup_provenance(project_root)
    plan = _resolve_and_validate(config)
    _generate_backends(config, plan, project_root, collector, quiet=quiet, dry_run=dry_run)
    _generate_frontend_phase(config, project_root, quiet=quiet)
    _render_docker_stack(config, plan, project_root, quiet=quiet)
    _generate_frontend_extras(config, project_root, quiet=quiet)
    _apply_project_scope(config, plan, project_root, collector, quiet=quiet)
    _finalize(config, plan, project_root, collector, quiet=quiet, dry_run=dry_run)
    return project_root


def _create_root(config: ProjectConfig, dry_run: bool) -> Path:
    """Resolve the project root directory and ensure it exists."""
    if dry_run:
        import tempfile  # noqa: PLC0415

        tmp_dir = Path(tempfile.mkdtemp(prefix="forge-dry-"))
        project_root = tmp_dir / config.project_slug
    else:
        project_root = Path(config.output_dir).resolve() / config.project_slug
    project_root.mkdir(parents=True, exist_ok=True)
    return project_root


def _setup_provenance(project_root: Path) -> ProvenanceCollector:
    """Create the per-file provenance collector for this generate() run.

    Per-file provenance for every write this run. Stamped into forge.toml
    at the end; the updater uses it to distinguish user-modified from
    fragment-modified files on subsequent `forge --update` runs.
    """
    return ProvenanceCollector(project_root=project_root)


def _resolve_and_validate(config: ProjectConfig) -> ResolvedPlan:
    """Resolve the capability plan and run static pre-flight validation.

    P1.3: static pre-flight check. Catches inject.yaml / env.yaml /
    file-overlap problems in <100ms before Copier runs (which takes
    ~5s per backend). Failures here surface every issue at once so
    plugin authors aren't stuck iterating through them serially.
    """
    with phase_timer(_logger, "generate.resolve"):
        plan = resolve(config)

    from forge.plan_validator import validate_plan  # noqa: PLC0415

    with phase_timer(_logger, "generate.validate_plan"):
        validate_plan(plan)
    return plan


def _generate_backends(
    config: ProjectConfig,
    plan: ResolvedPlan,
    project_root: Path,
    collector: ProvenanceCollector,
    *,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Render every backend: copier, provenance, fragments, strip, toolchain."""

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    for bc in config.backends:
        spec = BACKEND_REGISTRY[bc.language]
        backend_dir = project_root / "services" / bc.name
        _log(f"  Generating {spec.display_label} backend '{bc.name}' ...")
        with phase_timer(
            _logger,
            "generate.copier.backend",
            backend=bc.name,
            language=bc.language.value,
        ):
            # ``platform-auth`` is the runtime SDK the auth middleware
            # fragment imports from. It lives at ``sdks/platform-auth/``
            # (shipped by ``platform_auth_sdk_python``) and needs both a
            # ``"platform-auth"`` ``[project] dependencies`` entry and a
            # ``[tool.uv.sources]`` path-dep so ``uv sync`` resolves it
            # against the in-tree source. Flip the copier var only when
            # the Python middleware fragment is actually in the plan —
            # non-auth Python services don't ship sdks/platform-auth/ so
            # they'd uv-sync-fail if we always emitted the entry.
            includes_platform_auth = any(
                rf.fragment.name == "platform_auth_python_middleware" for rf in plan.ordered
            )
            _generate_single_backend(
                bc,
                spec.template_dir,
                backend_dir,
                quiet,
                include_platform_auth=includes_platform_auth,
            )
        # We know which backend template produced this tree (spec.template_dir
        # is e.g. "services/python-service-template"). Pass it as template_name
        # so harvest / drift-verify can attribute each file to its emitting
        # template. ``template_version`` is the resolved semver from
        # ``_forge_template.toml`` (or the BackendSpec default), so per-file
        # provenance entries record the version too — the updater compares
        # this against the live template at update time.
        backend_template_version = _resolve_template_version_for(
            spec.template_dir, spec.version
        )
        _record_tree(
            backend_dir,
            collector,
            origin="base-template",
            template_name=spec.template_dir,
            template_version=backend_template_version,
        )
        # Phase B1 + Cluster D (matrix-nightly-fixes plan): strip the database
        # stack from Python backends when ``database.mode=none`` BEFORE feature/
        # fragment application. The earlier order (strip after apply_features)
        # was a silent security regression — strippers write _STATELESS_LIFECYCLE
        # over the lifecycle.py that fragments like default-on pii_redaction had
        # just injected into, dropping the ``install_pii_filter()`` call without
        # any signal. With the strip running first, fragments inject into the
        # stateless lifecycle.py and the manifest correctly records each as the
        # fragment owner. The validator (``_validate_database_mode``) blocks
        # every stateless-incompatible fragment option so apply_features only
        # sees fragments that survive a stripped tree.
        if config.database_mode == "none" and bc.language == BackendLanguage.PYTHON:
            from forge.strippers import strip_python_database  # noqa: PLC0415

            _log(f"  Stripping DB stack from {bc.name} (database.mode=none) ...")
            strip_python_database(
                backend_dir,
                collector=collector,
                template_name=spec.template_dir,
                template_version=backend_template_version,
            )
        with phase_timer(
            _logger,
            "generate.apply_features",
            backend=bc.name,
            language=bc.language.value,
            fragment_count=len(plan.ordered),
        ):
            apply_features(
                bc,
                backend_dir,
                plan.ordered,
                quiet=quiet,
                collector=collector,
                option_values=plan.option_values,
                project_root=project_root,
            )
        # Toolchain dispatch: install() runs whenever we're writing to
        # disk (it's the step that produces lockfiles Docker needs),
        # verify() runs only in interactive mode (not quiet, not dry-run)
        # because it invokes lint + test suites that the headless path
        # shouldn't spend time on. Both are plugin-overridable via
        # ``BackendSpec.toolchain`` — see forge.toolchains.
        if not dry_run:
            with phase_timer(
                _logger,
                "generate.toolchain.install",
                backend=bc.name,
                language=bc.language.value,
            ):
                spec.toolchain.install(backend_dir, quiet=quiet)
        if not quiet and not dry_run:
            with phase_timer(
                _logger,
                "generate.toolchain.verify",
                backend=bc.name,
                language=bc.language.value,
            ):
                spec.toolchain.verify(backend_dir, quiet=quiet)
            spec.toolchain.post_generate(backend_dir, quiet=quiet)


def _generate_frontend_phase(config: ProjectConfig, project_root: Path, *, quiet: bool) -> None:
    """Phase 2: render the frontend via Copier when configured."""

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # 2. Generate frontend
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log(f"  Generating {config.frontend.framework.value} frontend ...")
        with phase_timer(
            _logger,
            "generate.copier.frontend",
            framework=config.frontend.framework.value,
        ):
            _generate_frontend(config, project_root, quiet=quiet)


def _render_docker_stack(
    config: ProjectConfig, plan: ResolvedPlan, project_root: Path, *, quiet: bool
) -> None:
    """Phase 3: render docker-compose, init-db, keycloak/gatekeeper assets."""

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # 3. Render Docker Compose
    #
    # Phase A: compose also renders for frontend-only projects (backend.mode=none
    # with a frontend framework) — the generated stack is frontend + traefik
    # (+ optional keycloak), pointing the browser at ``frontend.api_target.url``.
    # The template handles empty backends via ``{% if backends %}`` guards.
    has_frontend = (
        config.frontend is not None and config.frontend.framework != FrontendFramework.NONE
    )
    if config.backends or has_frontend or config.include_keycloak:
        _log("  Rendering docker-compose.yml ...")
        # P1.3 (1.1.0-alpha.2) — register any fragment-shipped
        # ``compose.yaml`` declarations into SERVICE_REGISTRY before
        # render_compose pulls capabilities into the docker-compose file.
        # Additive: built-in services declared imperatively in
        # docker-compose.yml.j2 still render via the existing template
        # path; fragments adopting compose.yaml light up alongside them.
        from forge.services.fragment_compose import (  # noqa: PLC0415
            fragment_roots_from_plan,
            register_fragment_services,
        )

        register_fragment_services(fragment_roots_from_plan(plan.ordered))
        # Workspace root manifests (npm + Cargo). Render before compose so
        # the compose entries' ``additional_contexts: { project_root: . }``
        # references resolve. Each renderer is a no-op when the project
        # has no consumer of its language (Python+Flutter-only skips both).
        render_workspace_package_json(config, project_root, plan=plan)
        render_workspace_cargo_toml(config, project_root, plan=plan)
        with phase_timer(_logger, "generate.compose.render"):
            render_compose(config, project_root, plan=plan)
        # init-db creates a database per backend plus keycloak's own db.
        # Skip when there are 0–1 backends and no keycloak — the primary
        # backend's POSTGRES_DB env var already handles the single-db case.
        # Phase B1: backend DBs don't need creating when database.mode=none;
        # init-db is only useful for keycloak's own database in that mode.
        need_multi_backend_init = len(config.backends) > 1 and config.database_mode != "none"
        if need_multi_backend_init or config.include_keycloak:
            _log("  Rendering init-db.sh ...")
            render_init_db(config, project_root)
        # Copy auth infrastructure if Keycloak is enabled
        if config.include_keycloak:
            # Render Keycloak realm JSON
            _log("  Rendering keycloak-realm.json ...")
            render_keycloak_realm(config, project_root)
            # Copy gatekeeper service
            _log("  Copying gatekeeper ...")
            gatekeeper_src = TEMPLATES_DIR / "infra" / "gatekeeper"
            gatekeeper_dst = project_root / "infra" / "gatekeeper"
            if gatekeeper_src.exists():
                shutil.copytree(str(gatekeeper_src), str(gatekeeper_dst), dirs_exist_ok=True)
            # Copy keycloak (Dockerfile + themes)
            _log("  Copying keycloak ...")
            keycloak_src = TEMPLATES_DIR / "infra" / "keycloak"
            keycloak_dst = project_root / "infra" / "keycloak"
            if keycloak_src.exists():
                shutil.copytree(str(keycloak_src), str(keycloak_dst), dirs_exist_ok=True)
            # Copy validate.sh (LF line endings for Linux containers)
            validate_src = (TEMPLATES_DIR / "infra" / "validate.sh").read_text(encoding="utf-8")
            validate_dst = project_root / "validate.sh"
            validate_dst.write_bytes(validate_src.replace("\r\n", "\n").encode("utf-8"))


def _generate_frontend_extras(config: ProjectConfig, project_root: Path, *, quiet: bool) -> None:
    """Phases 4 & 5: Playwright e2e tests + frontend Dockerfile/nginx."""

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # 4. Generate Playwright e2e tests
    if (
        config.frontend
        and config.frontend.framework != FrontendFramework.NONE
        and config.frontend.generate_e2e_tests
    ):
        _log("  Generating Playwright e2e tests ...")
        _generate_e2e_tests(config, project_root, quiet=quiet)

    # 5. Render frontend Dockerfile and nginx.conf (all frameworks)
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log("  Rendering frontend Dockerfile ...")
        frontend_dir = project_root / "apps" / config.frontend_slug
        render_frontend_dockerfile(config, frontend_dir)
        render_nginx_conf(config, frontend_dir)


def _apply_project_scope(
    config: ProjectConfig,
    plan: ResolvedPlan,
    project_root: Path,
    collector: ProvenanceCollector,
    *,
    quiet: bool,
) -> None:
    """Catch-all provenance sweep, project-scope features, shared files, codegen."""
    # Record any non-backend base-template writes (frontend, e2e, infra) so
    # the provenance manifest covers the full project tree, not just
    # backends. We scan everything outside services/ to avoid double-recording
    # backend files already tagged per-backend above.
    #
    # template_name is intentionally None here: this catch-all pass covers a
    # mix of templates (frontend, e2e, infra, common files written via
    # ``apply_common_files`` and codegen pipeline outputs that landed before
    # this scan). Attribution per-template happens in the dedicated record
    # paths (codegen.pipeline, common_files.apply_common_files). When the
    # frontend tree is reached here, the framework-specific template_name
    # could be threaded — TODO: split this catch-all into per-template
    # passes (frontend / e2e / infra) once those paths grow explicit
    # provenance hooks.
    _record_tree(
        project_root,
        collector,
        origin="base-template",
        skip_dirs=("services",),
        skip_if_recorded=True,
    )

    with phase_timer(_logger, "generate.apply_project_features"):
        apply_project_features(
            project_root,
            plan.ordered,
            quiet=quiet,
            collector=collector,
            option_values=plan.option_values,
            frontend_framework=(
                config.frontend.framework if config.frontend else FrontendFramework.NONE
            ),
        )

    # Drop shared quality-signal files (.editorconfig, .gitignore, CI, pre-commit)
    # if the per-template generators haven't already provided them.
    from forge.common_files import apply_common_files  # noqa: PLC0415

    apply_common_files(config, project_root, collector=collector)

    # Schema-first codegen: UI protocol types, canvas manifest, shared enums.
    # Runs last so per-template and fragment outputs don't clobber the
    # authoritative generated files. Failures are warnings — codegen
    # errors shouldn't take down a generation that's otherwise complete.
    from forge.codegen.pipeline import run_codegen  # noqa: PLC0415

    try:
        with phase_timer(_logger, "generate.codegen"):
            run_codegen(config, project_root, collector=collector)
    except Exception as exc:  # noqa: BLE001
        if not quiet:
            print(f"  [warn] codegen pipeline emitted an error: {exc}")


def _finalize(
    config: ProjectConfig,
    plan: ResolvedPlan,
    project_root: Path,
    collector: ProvenanceCollector,
    *,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Write forge.toml manifest and initialize the project git repository."""

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    with phase_timer(_logger, "generate.write_forge_toml"):
        _write_forge_toml(config, project_root, plan, collector=collector)

    if not dry_run:
        _log("  Initializing git repository ...")
        _cleanup_sub_git_repos(project_root)
        _git_init(project_root)


# Directories that frontend / backend toolchains create AFTER forge has
# finished generating — populated by ``npm install`` / ``cargo build`` /
# ``uv sync`` running inside the templates' ``post_generate.py``. None of
# their contents are forge-tracked artefacts, so the provenance manifest
# should not include them. Walking them is also extremely expensive
# (``node_modules`` alone can be 30k+ files post-install, each requiring
# a SHA-256 read).
_PROVENANCE_PRUNE_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".svelte-kit",
        ".next",
        "build",
        "dist",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
        "target",  # rust cargo build output
        ".dart_tool",  # flutter
        ".idea",
        ".vscode",
    }
)


def _record_tree(
    root: Path,
    collector: ProvenanceCollector,
    *,
    origin: str,
    skip_dirs: tuple[str, ...] = (),
    skip_if_recorded: bool = False,
    template_name: str | None = None,
    template_version: str | None = None,
) -> None:
    """Walk ``root`` and record every file as ``origin`` in the collector.

    ``skip_dirs`` names immediate children of ``root`` whose subtrees are
    excluded (e.g. ``services`` when recording top-level non-backend
    writes, since backends are recorded per-backend).

    :data:`_PROVENANCE_PRUNE_DIRS` is applied at ANY depth — these are
    toolchain build artefacts (``node_modules``, ``target``, ``build``,
    ``__pycache__``, ``.git``, etc.) that frontend / backend
    post_generate hooks create *after* forge has finished, so they're
    not forge-tracked and should never enter the provenance manifest.

    When ``skip_if_recorded=True``, paths already in the collector are
    not overwritten — useful for idempotent top-up scans after an earlier
    per-subtree pass already tagged some files with more specific origins.

    ``template_name`` / ``template_version`` are forwarded to each
    ``collector.record(...)`` call so per-file entries carry the
    emitting-template attribution. Pass ``None`` when the caller cannot
    cheaply identify a single template (e.g. mixed catch-all sweeps).
    """
    import os  # noqa: PLC0415

    from forge.sync.provenance import ProvenanceOrigin as _PO  # noqa: PLC0415

    origin_typed: _PO = origin  # type: ignore[assignment]  # ty:ignore[invalid-assignment]
    if not root.is_dir():
        return
    # ``os.walk`` with in-place ``dirnames`` mutation prunes whole
    # subtrees from traversal — orders of magnitude faster than
    # ``rglob`` + post-filter when ``node_modules`` (~30k files) is
    # present, since rglob descends into pruned directories and only
    # then drops their results.
    skip_top: set[str] = set(skip_dirs)
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune build-artefact directories at any depth.
        dirnames[:] = [d for d in dirnames if d not in _PROVENANCE_PRUNE_DIRS]
        # Prune top-level-only skips (relative to ``root``).
        current = Path(dirpath)
        if current == root:
            dirnames[:] = [d for d in dirnames if d not in skip_top]
        for name in filenames:
            p = current / name
            try:
                rel = p.relative_to(root)
            except ValueError:
                continue
            parts = rel.parts
            # Never record forge.toml itself — the provenance table references it.
            if parts and parts[-1] == "forge.toml" and len(parts) == 1:
                continue
            if skip_if_recorded:
                key = p.relative_to(collector.project_root).as_posix()
                if key in collector.records:
                    continue
            collector.record(
                p,
                origin=origin_typed,
                template_name=template_name,
                template_version=template_version,
            )


def _resolve_template_version_for(template_dir_rel: str, spec_default: str) -> str:
    """Resolve the template's effective version, preferring ``_forge_template.toml``.

    ``template_dir_rel`` is the path-under-``forge/templates/`` recorded
    on the spec (e.g. ``"services/python-service-template"``). The
    resolver reads that template's metadata file when present, falling
    back to ``spec_default`` (the spec's typed default).
    """
    from forge.sync.template_version import resolve_template_version  # noqa: PLC0415

    return resolve_template_version(
        TEMPLATES_DIR / template_dir_rel,
        spec_default=spec_default,
    )


def _write_forge_toml(
    config: ProjectConfig,
    project_root: Path,
    plan: ResolvedPlan | None = None,
    *,
    collector: ProvenanceCollector | None = None,
) -> None:
    """Write a forge.toml manifest at the project root.

    Records the forge version, template paths, and the fully-resolved
    ``options`` mapping (user-set values plus defaults). When a
    provenance ``collector`` is supplied, its records are emitted as the
    ``[forge.provenance]`` sub-tables.
    """
    from importlib import metadata  # noqa: PLC0415

    from forge.sync.manifest import write_forge_toml  # noqa: PLC0415

    try:
        forge_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        forge_version = "0.0.0+unknown"

    templates: dict[str, str] = {}
    template_versions: dict[str, str] = {}
    for lang in sorted({bc.language.value for bc in config.backends}):
        spec = BACKEND_REGISTRY[BackendLanguage(lang)]
        templates[lang] = spec.template_dir
        template_versions[lang] = _resolve_template_version_for(spec.template_dir, spec.version)
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        fw = config.frontend.framework
        template_dir = TEMPLATE_DIRS.get(fw)
        if template_dir:
            templates[fw.value] = template_dir
            # Built-in frontends don't carry a FrontendSpec (the generator
            # dispatches via TEMPLATE_DIRS, not FRONTEND_SPECS). Plugin
            # frontends do — look them up, otherwise treat as "1.0.0" so
            # the on-disk ``_forge_template.toml`` (or its absence) drives
            # resolution.
            from forge.config import FRONTEND_SPECS  # noqa: PLC0415

            frontend_spec = FRONTEND_SPECS.get(fw.value)
            spec_default = frontend_spec.version if frontend_spec is not None else "1.0.0"
            template_versions[fw.value] = _resolve_template_version_for(template_dir, spec_default)

    options: dict[str, Any] = dict(plan.option_values) if plan is not None else dict(config.options)
    # Origins: every path the caller supplied in ``config.options`` is
    # "user"; everything the resolver filled in (defaults) is "default".
    # This is the v3 schema's contract — Stage B (WS2b) of the per-
    # option-provenance fix needs the distinction so ``forge --update``
    # can re-read forge.toml and skip incompatible-backend fragments
    # whose option values came from defaults instead of user input.
    # When ``plan`` is None (no-resolve fallback path), options match
    # config.options 1:1 — every entry is by definition user-set.
    #
    # ``config.options`` may use alias paths (the resolver rewrites them
    # to canonical during resolve); ``options`` is always canonical-keyed.
    # Normalize aliases to canonical via ``resolve_alias`` so a user-set
    # alias path still records as ``"user"`` on the canonical key.
    from forge.options import resolve_alias  # noqa: PLC0415

    user_set_paths = {resolve_alias(p) or p for p in config.options}
    option_origins: dict[str, str] = {
        path: ("user" if path in user_set_paths else "default") for path in options
    }
    provenance = collector.as_dict() if collector is not None else None
    merge_blocks = collector.merge_blocks_as_dict() if collector is not None else None

    write_forge_toml(
        project_root / "forge.toml",
        version=forge_version,
        project_name=config.project_name,
        templates=templates,
        options=options,
        option_origins=option_origins,
        provenance=provenance,
        merge_blocks=merge_blocks,
        template_versions=template_versions,
    )


def _run_copier(template_path: Path, dst_path: Path, data: dict[str, Any], quiet: bool) -> None:
    """Invoke Copier and translate its failures into GeneratorError.

    After a successful copy, writes a ``.copier-answers.yml`` inside the
    rendered directory so ``forge update`` (or ``copier update`` directly)
    can compute a template-change diff later without re-prompting the
    user. Copier itself only emits the answers file if the template
    ships ``{{ _copier_conf.answers_file }}.jinja``; forge's templates
    don't, so we write it ourselves from the exact ``data`` dict we just
    passed in.

    Raised errors include the template path so JSON-mode callers see a useful
    envelope instead of a raw Copier traceback.
    """
    if not template_path.exists():
        raise TemplateError(
            f"Template not found: {template_path}",
            code=TEMPLATE_NOT_FOUND,
            context={"template": template_path.name, "template_path": str(template_path)},
        )
    try:
        run_copy(
            src_path=str(template_path),
            dst_path=str(dst_path),
            data=data,
            unsafe=True,
            defaults=True,
            overwrite=True,
            quiet=quiet,
        )
    except ForgeError:
        raise
    # Split fidelity so --json consumers can branch on code rather than regex
    # the message. CopierError covers template authoring bugs (bad copier.yml,
    # rejected validator, invalid Jinja inside the template). OSError covers
    # real filesystem failures (permission denied, disk full). RuntimeError
    # catches Jinja bubble-ups that Copier doesn't wrap (strict-undefined
    # access, filter exceptions). Anything else is a programming bug and
    # propagates unwrapped.
    except CopierError as e:
        raise TemplateError(
            f"Copier failed to render template '{template_path.name}': {e}",
            code=TEMPLATE_RENDER_FAILED,
            context={"template": template_path.name, "copier_type": type(e).__name__},
        ) from e
    except OSError as e:
        raise FilesystemError(
            f"Filesystem error while rendering template '{template_path.name}': {e}",
            code=FILESYSTEM_IO_ERROR,
            context={
                "template": template_path.name,
                "errno": getattr(e, "errno", None),
                "strerror": getattr(e, "strerror", None),
            },
        ) from e
    except RuntimeError as e:
        raise TemplateError(
            f"Template rendering failed (Jinja) for '{template_path.name}': {e}",
            code=TEMPLATE_JINJA_ERROR,
            context={"template": template_path.name, "runtime_type": type(e).__name__},
        ) from e

    _write_copier_answers(template_path, dst_path, data)


def _write_copier_answers(template_path: Path, dst_path: Path, data: dict[str, Any]) -> None:
    """Stamp a ``.copier-answers.yml`` matching Copier's schema.

    Keys starting with ``_`` are Copier-internal (``_src_path``, ``_commit``).
    User-supplied answers follow, alphabetically sorted for diff stability.
    """
    import yaml

    answers: dict[str, Any] = {"_src_path": str(template_path)}
    # Try to read the git commit at the template source, so `copier update`
    # can pin behavior. Non-repo sources (local directories not under git)
    # skip this silently.
    commit = _read_template_commit(template_path)
    if commit:
        answers["_commit"] = commit

    for key in sorted(data):
        val = data[key]
        # Drop non-serializable values (paths, enums) — Copier's own answers
        # file only records scalar / list / dict shapes.
        if isinstance(val, (str, int, float, bool)) or val is None:
            answers[key] = val
        elif isinstance(val, (list, tuple)):
            answers[key] = list(val)
        elif isinstance(val, dict):
            answers[key] = dict(val)
        else:
            answers[key] = str(val)

    out = dst_path / ".copier-answers.yml"
    header = (
        "# Changes here will be overwritten by forge / Copier on regenerate.\n"
        "# To re-render this subtree, run `copier update` from its directory\n"
        "# or `forge update` from the project root.\n"
    )
    out.write_text(header + yaml.safe_dump(answers, sort_keys=False), encoding="utf-8")


def _read_template_commit(template_path: Path) -> str | None:
    """Return ``git rev-parse HEAD`` for the template repo, if any."""
    import subprocess

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=template_path,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def _generate_e2e_tests(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate E2E testing platform using Copier template."""
    ctx = variable_mapper.e2e_context(config)
    dst = project_root / "tests" / "e2e"
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / "tests" / "e2e-testing-template", dst, ctx, quiet)
    return dst


def _generate_single_backend(
    bc: BackendConfig,
    template_name: str,
    dst: Path,
    quiet: bool = False,
    *,
    include_platform_auth: bool = False,
) -> Path:
    """Generate a single backend using Copier."""
    ctx = variable_mapper.backend_context(bc, include_platform_auth=include_platform_auth)
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / template_name, dst, ctx, quiet)
    return dst


def _generate_frontend(config: ProjectConfig, project_root: Path, quiet: bool = False) -> Path:
    """Generate frontend using Copier."""
    if config.frontend is None:
        raise GeneratorError("_generate_frontend called without a frontend configured")
    fw = config.frontend.framework
    template_dir = TEMPLATE_DIRS.get(fw)
    if template_dir is None:
        raise GeneratorError(f"No template for framework: {fw}")

    ctx = variable_mapper.frontend_context(config)

    # Templates that declare ``_subdirectory:`` render INTO dst_path
    # (Vue/Svelte + most plugin templates); templates without it own the
    # inner directory name (Flutter's ``{{project_slug}}/``) and need
    # dst_path set to the parent.
    if frontend_uses_subdirectory(fw):
        dst = project_root / "apps" / config.frontend_slug
    else:
        dst = project_root / "apps"
    dst.mkdir(parents=True, exist_ok=True)
    _run_copier(TEMPLATES_DIR / template_dir, dst, ctx, quiet)
    return project_root / "apps" / config.frontend_slug


def _run_backend_cmd(
    backend_dir: Path,
    cmd: list[str],
    description: str,
    *,
    required: bool = False,
) -> bool:
    """Run a command in the backend directory, printing status.

    When `required=True`, any failure (timeout, missing tool, non-zero exit) raises
    GeneratorError so the project isn't left in a half-built state. When
    `required=False` (default), failures are logged and skipped — appropriate for
    best-effort interactive setup steps like `cargo fmt --check` or `vitest run`.

    On Windows, Python's ``subprocess`` doesn't walk ``PATHEXT`` when
    resolving bare executable names, so ``npm`` (which ships as
    ``npm.cmd``) raises FileNotFoundError even when it's on PATH.
    ``shutil.which`` does walk PATHEXT, so resolve the executable
    up-front to pick up the right shim.
    """
    resolved = shutil.which(cmd[0])
    if resolved is not None:
        cmd = [resolved, *cmd[1:]]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(backend_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"{description} timed out (5m)"
        if required:
            raise GeneratorError(f"{msg} while running: {' '.join(cmd)}") from e
        print(f"  [!!] {msg}")
        return False
    except FileNotFoundError as e:
        msg = f"{description} skipped ({cmd[0]} not found)"
        if required:
            raise GeneratorError(
                f"required tool '{cmd[0]}' not found on PATH (needed for: {description})"
            ) from e
        print(f"  [!!] {msg}")
        return False
    if result.returncode == 0:
        print(f"  [ok] {description}")
        return True
    print(f"  [!!] {description} failed")
    stderr_tail = ""
    if result.stderr:
        stderr_tail = "\n".join(result.stderr.strip().splitlines()[-5:])
        for line in stderr_tail.splitlines():
            print(f"       {line}")
    if required:
        suffix = f"\n{stderr_tail}" if stderr_tail else ""
        raise GeneratorError(
            f"{description} failed (exit {result.returncode}): {' '.join(cmd)}{suffix}"
        )
    return False


def _force_remove_readonly(func, path, _exc_info):
    """Error handler for shutil.rmtree to clear read-only flags on Windows."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _cleanup_sub_git_repos(project_root: Path) -> None:
    """Remove .git directories from generated subdirectories (recursive)."""
    for git_dir in project_root.rglob(".git"):
        if git_dir.is_dir() and git_dir.parent != project_root:
            shutil.rmtree(git_dir, onerror=_force_remove_readonly)


def _git_init(project_root: Path) -> None:
    """Initialize a single git repo at the project root.

    Each git step (init, add, commit) is checked; a failure on any step raises
    GeneratorError so callers don't end up with a half-initialized repo or, worse,
    a 'success' return with no commit at all.
    """
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "forge",
        "GIT_AUTHOR_EMAIL": "forge@localhost",
        "GIT_COMMITTER_NAME": "forge",
        "GIT_COMMITTER_EMAIL": "forge@localhost",
    }
    for step, cmd, step_env in (
        ("init", ["git", "init"], None),
        ("add", ["git", "add", "."], None),
        ("commit", ["git", "commit", "-m", "Initial commit from forge"], env),
    ):
        try:
            subprocess.run(
                cmd,
                cwd=str(project_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                # 120s timeout — ``git add`` on a freshly-scaffolded project
                # with the workspace SDK trees runs a few thousand
                # ``hashAndCacheFile`` calls under cold I/O. Windows
                # runners with NTFS + AV scanning have been observed
                # taking 60s+ on first staging pass (30s tripped first,
                # then 60s). 120s gives margin without inflating the test
                # budget — the matrix CI per-cell wall-clock is 5min+.
                timeout=120,
                check=True,
                env=step_env,
            )
        except FileNotFoundError as e:
            raise GeneratorError(
                "git executable not found on PATH; install git to scaffold a project"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise GeneratorError(f"git {step} timed out after 120s") from e
        except subprocess.CalledProcessError as e:
            stderr_tail = ""
            if e.stderr:
                stderr_tail = "\n".join(str(e.stderr).strip().splitlines()[-5:])
            suffix = f"\n{stderr_tail}" if stderr_tail else ""
            raise GeneratorError(f"git {step} failed (exit {e.returncode}){suffix}") from e

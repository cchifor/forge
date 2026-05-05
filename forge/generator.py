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
from forge.feature_injector import apply_features, apply_project_features
from forge.logging import get_logger, phase_timer
from forge.provenance import ProvenanceCollector

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
    if dry_run:
        import tempfile  # noqa: PLC0415

        tmp_dir = Path(tempfile.mkdtemp(prefix="forge-dry-"))
        project_root = tmp_dir / config.project_slug
    else:
        project_root = Path(config.output_dir).resolve() / config.project_slug
    project_root.mkdir(parents=True, exist_ok=True)

    def _log(msg: str) -> None:
        if not quiet:
            print(msg)

    # Per-file provenance for every write this run. Stamped into forge.toml
    # at the end; the updater uses it to distinguish user-modified from
    # fragment-modified files on subsequent `forge --update` runs.
    collector = ProvenanceCollector(project_root=project_root)

    with phase_timer(_logger, "generate.resolve"):
        plan = resolve(config)

    # P1.3: static pre-flight check. Catches inject.yaml / env.yaml /
    # file-overlap problems in <100ms before Copier runs (which takes
    # ~5s per backend). Failures here surface every issue at once so
    # plugin authors aren't stuck iterating through them serially.
    from forge.plan_validator import validate_plan  # noqa: PLC0415

    with phase_timer(_logger, "generate.validate_plan"):
        validate_plan(plan)

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
            _generate_single_backend(bc, spec.template_dir, backend_dir, quiet)
        _record_tree(backend_dir, collector, origin="base-template")
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
        # Phase B1: strip the database stack from Python backends when
        # ``database.mode=none``. Runs after fragment application so
        # fragments see the full template (config validation has
        # already blocked every DB-consuming fragment combo); runs
        # before ``toolchain.install`` so ``uv sync`` operates on the
        # already-stripped ``pyproject.toml`` and no SQLAlchemy/alembic
        # deps are resolved.
        if config.database_mode == "none" and bc.language == BackendLanguage.PYTHON:
            from forge.strippers import strip_python_database  # noqa: PLC0415

            _log(f"  Stripping DB stack from {bc.name} (database.mode=none) ...")
            strip_python_database(backend_dir)
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

    # 2. Generate frontend
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        _log(f"  Generating {config.frontend.framework.value} frontend ...")
        with phase_timer(
            _logger,
            "generate.copier.frontend",
            framework=config.frontend.framework.value,
        ):
            _generate_frontend(config, project_root, quiet=quiet)

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

    # Record any non-backend base-template writes (frontend, e2e, infra) so
    # the provenance manifest covers the full project tree, not just
    # backends. We scan everything outside services/ to avoid double-recording
    # backend files already tagged per-backend above.
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

    with phase_timer(_logger, "generate.write_forge_toml"):
        _write_forge_toml(config, project_root, plan, collector=collector)

    if not dry_run:
        _log("  Initializing git repository ...")
        _cleanup_sub_git_repos(project_root)
        _git_init(project_root)

    return project_root


def _record_tree(
    root: Path,
    collector: ProvenanceCollector,
    *,
    origin: str,
    skip_dirs: tuple[str, ...] = (),
    skip_if_recorded: bool = False,
) -> None:
    """Walk ``root`` and record every file as ``origin`` in the collector.

    ``skip_dirs`` names immediate children of ``root`` whose subtrees are
    excluded (e.g. ``services`` when recording top-level non-backend
    writes, since backends are recorded per-backend).

    When ``skip_if_recorded=True``, paths already in the collector are
    not overwritten — useful for idempotent top-up scans after an earlier
    per-subtree pass already tagged some files with more specific origins.
    """
    from forge.provenance import ProvenanceOrigin as _PO  # noqa: PLC0415

    origin_typed: _PO = origin  # type: ignore[assignment]  # ty:ignore[invalid-assignment]
    if not root.is_dir():
        return
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        # Never record forge.toml itself — the provenance table references it.
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if parts and parts[0] in skip_dirs:
            continue
        if parts and parts[-1] == "forge.toml" and len(parts) == 1:
            continue
        if skip_if_recorded:
            key = p.relative_to(collector.project_root).as_posix()
            if key in collector.records:
                continue
        collector.record(p, origin=origin_typed)


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

    from forge.forge_toml import write_forge_toml  # noqa: PLC0415

    try:
        forge_version = metadata.version("forge")
    except metadata.PackageNotFoundError:
        forge_version = "0.0.0+unknown"

    templates: dict[str, str] = {}
    for lang in sorted({bc.language.value for bc in config.backends}):
        templates[lang] = BACKEND_REGISTRY[BackendLanguage(lang)].template_dir
    if config.frontend and config.frontend.framework != FrontendFramework.NONE:
        fw = config.frontend.framework
        template_dir = TEMPLATE_DIRS.get(fw)
        if template_dir:
            templates[fw.value] = template_dir

    options: dict[str, Any] = dict(plan.option_values) if plan is not None else dict(config.options)
    provenance = collector.as_dict() if collector is not None else None
    merge_blocks = collector.merge_blocks_as_dict() if collector is not None else None

    write_forge_toml(
        project_root / "forge.toml",
        version=forge_version,
        project_name=config.project_name,
        templates=templates,
        options=options,
        provenance=provenance,
        merge_blocks=merge_blocks,
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
    bc: BackendConfig, template_name: str, dst: Path, quiet: bool = False
) -> Path:
    """Generate a single backend using Copier."""
    ctx = variable_mapper.backend_context(bc)
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
                timeout=30,
                check=True,
                env=step_env,
            )
        except FileNotFoundError as e:
            raise GeneratorError(
                "git executable not found on PATH; install git to scaffold a project"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise GeneratorError(f"git {step} timed out after 30s") from e
        except subprocess.CalledProcessError as e:
            stderr_tail = ""
            if e.stderr:
                stderr_tail = "\n".join(str(e.stderr).strip().splitlines()[-5:])
            suffix = f"\n{stderr_tail}" if stderr_tail else ""
            raise GeneratorError(f"git {step} failed (exit {e.returncode}){suffix}") from e

"""Template re-render driver — Copier base-template update tasks.

Split out from the original ``updater.py`` god module — see
:mod:`forge.sync.forge_to_project.updater` for the public surface.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forge.config import BackendConfig
from forge.sync.manifest import ForgeTomlData


def _build_template_update_tasks(
    *,
    project_root: Path,
    data: ForgeTomlData,
    backends: list[BackendConfig],
) -> list[Any]:
    """Compare recorded vs. live template versions and enqueue tasks.

    For each language in :attr:`ForgeTomlData.template_versions`, look
    up the current template version from the registry (preferring
    ``_forge_template.toml`` under ``forge/templates/<dir>``). If the
    recorded version differs from the current, build a
    :class:`TemplateUpdateTask` for the corresponding target directory
    on disk. Frontends use ``apps/<framework>/`` (or the conventional
    ``apps/<framework_slug>/``); backends use ``services/<backend>/``.

    Returns the (possibly empty) list of tasks. The list is empty when
    every recorded version matches the live one — no Copier work is
    required in that case.
    """
    # Importing the generator's TEMPLATES_DIR + TEMPLATE_DIRS would
    # create a circular import (generator → updater hooks via the CLI),
    # so we resolve the templates root and the frontend dispatch
    # table from forge.templates directly.
    import forge as _forge  # noqa: PLC0415
    from forge.config import (  # noqa: PLC0415
        BACKEND_REGISTRY,
        FRONTEND_SPECS,
        FrontendFramework,
        resolve_backend_language,
    )
    from forge.sync.forge_to_project.template_update import (  # noqa: PLC0415
        TemplateUpdateTask,
    )
    from forge.sync.template_version import resolve_template_version  # noqa: PLC0415

    templates_root = Path(_forge.__file__).parent / "templates"
    # Mirror the generator's frontend dispatch so we resolve framework
    # → template_dir without importing the generator.
    frontend_dispatch: dict[str, str] = {
        FrontendFramework.VUE.value: "apps/vue-frontend-template",
        FrontendFramework.SVELTE.value: "apps/svelte-frontend-template",
        FrontendFramework.FLUTTER.value: "apps/flutter-frontend-template",
    }

    tasks: list[Any] = []
    backend_languages = {bc.language.value for bc in backends}

    for lang, recorded_version in sorted(data.template_versions.items()):
        # Resolve the template's path + current version.
        template_path: Path | None = None
        spec_default = "1.0.0"

        # Backend language? ``resolve_backend_language`` (not the
        # ``BackendLanguage`` constructor) so a plugin-registered language
        # in the manifest resolves to its sentinel and gets update-checked,
        # instead of silently falling into the ``None`` branch and being
        # skipped. A genuinely unknown value (plugin uninstalled) still
        # raises ValueError → None → skip.
        try:
            backend_lang = resolve_backend_language(lang)
        except ValueError:
            backend_lang = None  # type: ignore[assignment]
        if backend_lang is not None and lang in backend_languages:
            spec = BACKEND_REGISTRY[backend_lang]
            template_path = templates_root / spec.template_dir
            spec_default = spec.version
        elif lang in frontend_dispatch:
            template_path = templates_root / frontend_dispatch[lang]
        elif lang in FRONTEND_SPECS:
            fspec = FRONTEND_SPECS[lang]
            template_path = templates_root / fspec.template_dir
            spec_default = fspec.version

        if template_path is None or not template_path.is_dir():
            # Plugin template the registry no longer ships, or the
            # path drifted — leave the recorded version untouched and
            # skip silently. The verify command surfaces this kind of
            # drift separately.
            continue

        current_version = resolve_template_version(template_path, spec_default=spec_default)
        if current_version == recorded_version:
            continue

        # Resolve the target directory on disk.
        target_dir: Path | None = None
        if backend_lang is not None:
            # Find the matching backend by language.
            for bc in backends:
                if bc.language.value == lang:
                    candidate = project_root / "services" / bc.name
                    if candidate.is_dir():
                        target_dir = candidate
                        break
        else:
            # Frontend: prefer the manifest's recorded ``app_dir`` if it
            # exists (Initiative #3, v4 manifest). Falls back to the
            # conventional ``apps/<framework_slug>/`` slot, then to
            # scanning ``apps/`` for any directory with a
            # ``.copier-answers.yml`` — the pre-Init-#3 behavior.
            recorded_app_dir = data.frontend.app_dir
            if recorded_app_dir:
                candidate = project_root / recorded_app_dir
                if (candidate / ".copier-answers.yml").is_file():
                    target_dir = candidate
            apps = project_root / "apps"
            if target_dir is None and apps.is_dir():
                # Try the direct framework subdir first, then fall back
                # to scanning for the first apps/<dir>/.copier-answers.yml.
                framework_dir = apps / lang
                if (framework_dir / ".copier-answers.yml").is_file():
                    target_dir = framework_dir
                else:
                    for sub in sorted(apps.iterdir()):
                        if not sub.is_dir():
                            continue
                        if (sub / ".copier-answers.yml").is_file():
                            target_dir = sub
                            break

        if target_dir is None or not target_dir.is_dir():
            continue
        if not (target_dir / ".copier-answers.yml").is_file():
            # Without answers, ``copier update`` has no input. Skip
            # silently — the project predates answer-file emission, or
            # the user removed it.
            continue

        tasks.append(
            TemplateUpdateTask(
                language=lang,
                project_version=recorded_version,
                current_version=current_version,
                target_dir=target_dir,
                template_src=template_path,
            )
        )
    return tasks

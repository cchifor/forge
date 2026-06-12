"""`forge add-backend --language <lang> --name <name>` — scaffold an extra backend.

Reads the project's existing ``forge.toml`` to learn the project shape,
then regenerates JUST the new backend by running the normal generator
with a one-backend ProjectConfig whose ``output_dir`` points at the
project root. The existing backends and frontend are untouched — the
generator skips a directory that already exists.

Post-scaffold, the user is expected to:

  1. Register the new backend in docker-compose.yml (if using Docker)
  2. Wire it into the Vite proxy config (if a Vue/Svelte frontend exists)
  3. Re-run ``forge --update`` to refresh the provenance manifest
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from forge.config import BackendLanguage


def _dispatch_add_backend(args) -> None:
    language = getattr(args, "add_backend_language", None)
    name = getattr(args, "add_backend_name", None)
    project_path = Path(getattr(args, "project_path", ".")).resolve()

    # Validate against every registered language (built-ins + plugin
    # backends loaded earlier in ``main()``), not a hardcoded triple — a
    # plugin that registered ``go`` makes ``--add-backend-language go`` valid.
    from forge.config import available_backend_languages  # noqa: PLC0415

    valid_languages = available_backend_languages()
    if language not in valid_languages:
        print(
            f"error: --add-backend-language must be one of "
            f"{'|'.join(valid_languages)}, got {language!r}",
            file=sys.stderr,
        )
        sys.exit(2)
    if not name:
        print("error: --add-backend-name is required", file=sys.stderr)
        sys.exit(2)

    backend_dir = project_path / "services" / name
    if backend_dir.exists():
        print(
            f"error: services/{name} already exists. Pick a different --add-backend-name.",
            file=sys.stderr,
        )
        sys.exit(2)

    from forge.config import (  # noqa: PLC0415
        BACKEND_REGISTRY,  # noqa: PLC0415
        BackendConfig,
        resolve_backend_language,
    )
    from forge.generator import _generate_single_backend  # noqa: PLC0415
    from forge.sync.manifest import read_forge_toml  # noqa: PLC0415

    manifest = project_path / "forge.toml"
    if not manifest.is_file():
        print(
            f"error: no forge.toml at {project_path}. Run inside a forge-generated project.",
            file=sys.stderr,
        )
        sys.exit(2)

    data = read_forge_toml(manifest)
    project_name = data.project_name or project_path.name

    lang_enum = resolve_backend_language(language)
    bc = BackendConfig(
        name=name,
        project_name=project_name,
        # cast: a plugin language is a _PluginLanguage sentinel that behaves
        # like a BackendLanguage member at runtime (registry key, ``.value``)
        # but isn't statically one. See forge.config.resolve_backend_language.
        language=cast("BackendLanguage", lang_enum),
        features=["items"],
        server_port=5000,
    )

    spec = BACKEND_REGISTRY[lang_enum]

    # E.1.b parity: if the project opted into the error_port runtime
    # wiring (``observability.error_envelope=True``), the new backend
    # must match — otherwise the new service silently ships the inline
    # serialiser while peer services route through ``DefaultErrorPort``,
    # breaking the per-project consistency the port promises. The main
    # generator derives this from plan membership of the ``error_port``
    # fragment; here we read the option directly from the manifest
    # because ``add-backend`` doesn't run the full capability resolver.
    # Default ``False`` is fail-safe — matches the variable_mapper
    # default and avoids emitting ``use crate::error_port::...`` (Rust)
    # in projects where the port module isn't on disk. (Codex Phase B
    # round 2 finding.)
    include_error_envelope = bool(data.options.get("observability.error_envelope", False))

    print(f"Scaffolding {spec.display_label} backend '{name}' at {backend_dir} ...")
    _generate_single_backend(
        bc,
        spec.template_dir,
        backend_dir,
        quiet=False,
        include_error_envelope=include_error_envelope,
    )

    print()
    print("Next steps:")
    print(f"  1. cd services/{name} && <language-specific setup>")
    print("  2. Add the new service to docker-compose.yml (if you use Docker)")
    print("  3. Register its routes in the Vite proxy config (if you have a web frontend)")
    print("  4. Run `forge --update` to refresh forge.toml provenance")
    sys.exit(0)

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


def _dispatch_add_backend(args) -> None:
    language = getattr(args, "add_backend_language", None)
    name = getattr(args, "add_backend_name", None)
    project_path = Path(getattr(args, "project_path", ".")).resolve()

    if language not in ("python", "node", "rust"):
        print(
            f"error: --add-backend-language must be python|node|rust, got {language!r}",
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
        BackendLanguage,
    )
    from forge.forge_toml import read_forge_toml  # noqa: PLC0415
    from forge.generator import _generate_single_backend  # noqa: PLC0415

    manifest = project_path / "forge.toml"
    if not manifest.is_file():
        print(
            f"error: no forge.toml at {project_path}. Run inside a forge-generated project.",
            file=sys.stderr,
        )
        sys.exit(2)

    data = read_forge_toml(manifest)
    project_name = data.project_name or project_path.name

    lang_enum = BackendLanguage(language)
    bc = BackendConfig(
        name=name,
        project_name=project_name,
        language=lang_enum,
        features=["items"],
        server_port=5000,
    )

    spec = BACKEND_REGISTRY[lang_enum]
    print(f"Scaffolding {spec.display_label} backend '{name}' at {backend_dir} ...")
    _generate_single_backend(bc, spec.template_dir, backend_dir, quiet=False)

    print()
    print("Next steps:")
    print(f"  1. cd services/{name} && <language-specific setup>")
    print("  2. Add the new service to docker-compose.yml (if you use Docker)")
    print("  3. Register its routes in the Vite proxy config (if you have a web frontend)")
    print("  4. Run `forge --update` to refresh forge.toml provenance")
    sys.exit(0)

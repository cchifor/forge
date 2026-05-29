"""Shared constants + small validators used across config submodules.

Lives in its own module so the backend/frontend/project submodules can
import it without creating an import cycle. Has zero deps on the rest
of ``forge.config``.
"""

from __future__ import annotations

import keyword
import os
import re

# Keycloak realm that maps to Host(`app.localhost`) for Gatekeeper tenant extraction.
# Used as both the default user-facing realm name and the template fallback.
DEFAULT_REALM = "app"

# Traefik dashboard host port. Kept in sync with `deploy/docker-compose.yml.j2`.
TRAEFIK_DASHBOARD_PORT = 19090


def keycloak_client_id_from(project_name: str) -> str:
    """Normalize a project name into a Keycloak client ID (hyphen-separated, lowercase)."""
    return project_name.lower().replace(" ", "-").replace("_", "-")


def validate_port(port: int, name: str = "Port") -> None:
    if not (1024 <= port <= 65535):
        raise ValueError(f"{name} must be between 1024 and 65535, got {port}")


def validate_features(features: list[str]) -> None:
    seen: set[str] = set()
    for f in features:
        f = f.strip()
        if not f:
            continue
        if not re.match(r"^[a-z][a-z0-9_]*$", f):
            raise ValueError(
                f"Feature '{f}' must be lowercase, start with a letter, "
                "and contain only letters, digits, and underscores."
            )
        if keyword.iskeyword(f):
            raise ValueError(f"Feature '{f}' is a Python keyword.")
        if f in seen:
            raise ValueError(f"Duplicate feature: '{f}'")
        seen.add(f)


def validate_slug(slug: str) -> None:
    """Reject derived project slugs that could escape the output directory.

    ``project_slug`` is joined directly onto ``output_dir`` during generation,
    so a slug containing a path separator or that is a parent-directory segment
    would let a crafted project name write outside the intended tree. The slug
    is *derived* (lowercased, spaces/hyphens → underscores), so this guards the
    slug rather than imposing a strict regex on the human-facing project name
    (ordinary names like "My Platform" must keep working).
    """
    if not slug or slug in (".", ".."):
        raise ValueError(
            f"Project name derives an unusable slug {slug!r}; "
            "choose a name with at least one letter or digit."
        )
    seps = {"/", "\\", os.sep}
    if os.altsep:
        seps.add(os.altsep)
    if any(sep in slug for sep in seps):
        raise ValueError(
            f"Project name derives a slug {slug!r} containing a path separator; "
            "use only letters, digits, spaces, hyphens, and underscores."
        )

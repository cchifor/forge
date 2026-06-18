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

# Host ports the compose template (`deploy/docker-compose.yml.j2`) publishes
# for infra services. Kept in lockstep with the template so the port-collision
# validator neither rejects a free host port nor admits a real
# `docker compose up` collision. Postgres/pgAdmin/Redis bind to non-default
# host ports on purpose — the conventional 5432/6379 are the *container* ports
# and never appear on the host.
TRAEFIK_DASHBOARD_PORT = 19090
POSTGRES_HOST_PORT = 15432
PGADMIN_HOST_PORT = 5050
REDIS_HOST_PORT = 6379
GATEKEEPER_HOST_PORT = 5000


def infra_host_port_reservations(
    *, render_postgres: bool, include_keycloak: bool, keycloak_port: int
) -> dict[int, str]:
    """Host ports the compose stack publishes for infra services.

    Mirrors ``deploy/docker-compose.yml.j2``:

    - Traefik renders unconditionally — its dashboard binds
      ``TRAEFIK_DASHBOARD_PORT``.
    - Postgres + pgAdmin render only when ``render_postgres``
      (see :func:`forge.config._topology.compute_render_postgres`),
      publishing ``POSTGRES_HOST_PORT`` / ``PGADMIN_HOST_PORT``.
    - Redis, Gatekeeper and Keycloak render only with ``include_keycloak``.

    The container ports (5432/6379) are deliberately NOT reserved — only the
    published host binds can collide with a backend/frontend host port. The
    Traefik web port (80) is below the 1024 floor ``validate_port`` enforces,
    so a backend/frontend can never land on it.
    """
    reserved: dict[int, str] = {TRAEFIK_DASHBOARD_PORT: "Traefik dashboard"}
    if render_postgres:
        reserved[POSTGRES_HOST_PORT] = "PostgreSQL"
        reserved[PGADMIN_HOST_PORT] = "pgAdmin"
    if include_keycloak:
        reserved[REDIS_HOST_PORT] = "Redis"
        reserved[GATEKEEPER_HOST_PORT] = "Gatekeeper"
        # Detect a collision on insert rather than silently overwriting another
        # infra service's reservation: a user-chosen keycloak_port equal to a
        # fixed infra host bind (e.g. Gatekeeper 5000) would otherwise be lost
        # here, pass _validate_ports, then fail `docker compose up` with
        # "port is already allocated". (audit #21)
        if keycloak_port in reserved:
            raise ValueError(
                f"Keycloak port {keycloak_port} collides with the "
                f"{reserved[keycloak_port]} host port. Choose a different keycloak_port."
            )
        reserved[keycloak_port] = "Keycloak"
    return reserved


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

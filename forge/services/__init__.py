"""Service registry — capability → docker-compose service declarations.

See `forge.services.registry` for the data model and `forge.api.ForgeAPI.add_service`
for the plugin hook. Fragment-shipped ``compose.yaml`` declarations
(P1.3, 1.1.0-alpha.2) live in ``forge.services.fragment_compose``.
"""

from forge.services.fragment_compose import (
    FragmentComposeError,
    fragment_roots_from_plan,
    load_fragment_compose,
    register_fragment_services,
)
from forge.services.registry import (
    SERVICE_REGISTRY,
    ServiceTemplate,
    get_services_for_capabilities,
    register_service,
)

__all__ = [
    "FragmentComposeError",
    "SERVICE_REGISTRY",
    "ServiceTemplate",
    "fragment_roots_from_plan",
    "get_services_for_capabilities",
    "load_fragment_compose",
    "register_fragment_services",
    "register_service",
]

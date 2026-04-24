"""Service registry — capability → docker-compose service declarations.

See `forge.services.registry` for the data model and `forge.api.ForgeAPI.add_service`
for the plugin hook.
"""

from forge.services.registry import (
    SERVICE_REGISTRY,
    ServiceTemplate,
    get_services_for_capabilities,
    register_service,
)

__all__ = [
    "SERVICE_REGISTRY",
    "ServiceTemplate",
    "get_services_for_capabilities",
    "register_service",
]

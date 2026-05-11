"""Build a :class:`weld.connectors.ConnectorRegistry` for this service.

The registry is app-scoped (one per service) and pre-populated with the
builtins selected at generation time via ``connectors.backends``. Add
service-specific adapters by calling ``registry.register(...)`` from
:mod:`app.core.lifecycle` before yielding from the lifespan.
"""

from __future__ import annotations

from weld.connectors import ConnectorRegistry, build_default_connector_registry


def build_connector_registry() -> ConnectorRegistry:
    {%- if "http" in connectors_backends or "fs" in connectors_backends or "sql" in connectors_backends or "s3" in connectors_backends or "mcp" in connectors_backends %}
    return build_default_connector_registry(
        {%- for bk in connectors_backends %}
        enable_{{ bk }}=True,
        {%- endfor %}
    )
    {%- else %}
    return ConnectorRegistry()
    {%- endif %}

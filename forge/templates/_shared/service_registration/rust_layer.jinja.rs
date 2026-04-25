{# RFC-009 service-registration macro for Rust / Axum backends.

Renders an Axum extension. Singletons become `Arc<T>` registered on
the router via `.layer(Extension(Arc::new(...)))`; request-scoped
services emit a `FromRequestParts` extractor placeholder that the
fragment fills in.

Required `service` keys:
  - name           — snake_case identifier
  - type           — Rust struct / trait name
  - import_path    — Rust module path (e.g. `crate::services::anthropic`)
  - scope          — singleton | request | transient
  - dependencies   — list of other registered service `name`s; reified as
                     `Arc<DepType>` parameters
  - config_key     — dotted AppConfig path; resolved via `&AppConfig`

Optional:
  - startup        — when true, eager-instantiate before `Router::new()`
                     consumes it
  - shutdown_hook  — currently informational; Axum doesn't surface a
                     clean per-router shutdown hook
#}
{%- macro layer(service) -%}
use std::sync::Arc;
use axum::Extension;
use {{ service.import_path }}::{{ service.type }};
{%- if service.config_key %}
use crate::config::AppConfig;
{%- endif %}

pub fn {{ service.name }}_layer(
    {%- if service.config_key %}config: &AppConfig,{% endif -%}
    {%- for dep in service.dependencies %}{{ dep }}: Arc<dyn std::any::Any + Send + Sync>,{% endfor -%}
) -> Extension<Arc<{{ service.type }}>> {
    let instance = {{ service.type }}::new(
        {%- if service.config_key %}&config.{{ service.config_key }}{% endif -%}
        {%- for dep in service.dependencies %}, {{ dep }}{% endfor -%}
    );
    Extension(Arc::new(instance))
}
{%- endmacro %}

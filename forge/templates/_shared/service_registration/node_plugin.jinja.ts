{# RFC-009 service-registration macro for Node / Fastify backends.

Renders a Fastify plugin that decorates the app (singleton scope) or
the request (request / transient scope) with the service instance.
The fragment supplies the implementation class; this macro emits only
the registration boilerplate.

Required `service` keys:
  - name           — camelCase identifier (used as decoration key)
  - type           — TypeScript class / interface name
  - import_path    — relative module path (without extension); the macro
                     appends `.js` for ESM
  - scope          — singleton | request | transient
  - dependencies   — list of other registered service `name`s; resolved
                     via `app.<dep>`
  - config_key     — dotted AppConfig path; pulled from `appConfig.<key>`

Optional:
  - startup        — when true, eager-instantiate on `onReady` hook
  - shutdown_hook  — method called via `onClose` hook
#}
{%- macro plugin(service) -%}
import fastifyPlugin from "fastify-plugin";
import { {{ service.type }} } from "{{ service.import_path }}.js";
{%- if service.config_key %}
import { appConfig } from "../config/index.js";
{%- endif %}

declare module "fastify" {
  interface FastifyInstance {
    {{ service.name }}: {{ service.type }};
  }
}

export const {{ service.name }}Plugin = fastifyPlugin(async (app) => {
  const instance = new {{ service.type }}({
    {%- if service.config_key %}config: appConfig.{{ service.config_key }},{% endif -%}
    {%- for dep in service.dependencies %}{{ dep }}: app.{{ dep }},{% endfor -%}
  });

  {%- if service.scope == "singleton" %}
  app.decorate("{{ service.name }}", instance);
  {%- else %}
  app.decorateRequest("{{ service.name }}", null);
  app.addHook("onRequest", async (req) => {
    (req as { {{ service.name }}: {{ service.type }} }).{{ service.name }} = instance;
  });
  {%- endif %}

  {%- if service.shutdown_hook %}
  app.addHook("onClose", async () => {
    await instance.{{ service.shutdown_hook }}();
  });
  {%- endif %}
});
{%- endmacro %}

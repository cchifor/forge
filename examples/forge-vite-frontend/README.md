# forge-vite-frontend

A **reference forge plugin** that adds a new frontend **framework** — Vite
(vanilla TypeScript) — through the public plugin SDK. The frontend-surface
companion to [`forge-go-backend`](../forge-go-backend).

## What it shows

- `forge.api.ForgeAPI.add_frontend(value, spec)` registering a new framework so
  `forge --frontend vite` generates a real, buildable SPA — no fork of forge.
- A `FrontendSpec` declaring `template_dir` (absolute, resolved from
  `__file__`), `node_based`, `build_dir`, and `package_manager` — the metadata
  forge's compose / Dockerfile / npm-workspace wiring reads for a plugin
  frontend.
- Shipping the Copier template as package data.

## Install & use

```bash
pip install -e examples/forge-vite-frontend          # editable, for local dev
forge --frontend vite --backend-language python --output-dir ./my-app
cd my-app/apps/frontend && npm install && npm run build
```

A plugin frontend is a Copier-only render (no forge-specific auth/api hooks);
forge feeds it a generic context (project identity, resolved API base/proxy
URLs, server port) via `variable_mapper.plugin_frontend_context`.

## Layout

```
src/forge_vite_frontend/
  __init__.py              register(api) → api.add_frontend("vite", FrontendSpec(...))
  vite-frontend-template/  the Copier template forge renders
    copier.yml
    _forge_template.toml
    template/
      package.json.jinja
      index.html.jinja
      vite.config.ts.jinja
      tsconfig.json
      src/main.ts.jinja
      README.md.jinja
      .gitignore
```

# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in forge (the CLI tool, generated
project templates, or shipped SDK packages), please report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

### Preferred: GitHub Security Advisory

1. Go to https://github.com/cchifor/forge/security/advisories
2. Click "New draft security advisory"
3. Fill in the details

### Alternative: Email

Send details to chifor@gmail.com with subject line `[SECURITY] forge: <brief description>`.

## Response Timeline

- **Acknowledgement:** within 48 hours
- **Triage and severity assessment:** within 5 business days
- **Fix or mitigation:** within 30 days for critical/high severity

## Scope

This policy covers:

- The `forge` CLI and its Python package
- Generated project templates (service templates, frontend templates)
- Published SDK packages (`@forge/canvas-core`, `@forge/canvas-vue`,
  `@forge/canvas-svelte`, `forge_canvas`, `forge_canvas_core`)
- The plugin SDK (`ForgeAPI`)

## Disclosure

We follow coordinated disclosure. Reporters will be credited in the
advisory and release notes unless they prefer otherwise.

# Plugin SDK Changelog

This file tracks changes to the **plugin SDK surface** — the names and
signatures listed in ``forge/api.py``'s ``__all__``. The SDK version
lives at ``forge.api.SDK_VERSION`` and is independent of the forge
package version: a forge package release that doesn't touch the API
surface leaves SDK_VERSION unchanged.

Plugin authors target the SDK via ``api.require_sdk(">=X.Y")`` at the
top of their ``register()`` function. Bumps to SDK_VERSION require a
matching entry below; ``tests/test_sdk_version.py::test_sdk_changelog_exists``
asserts this file is present, and PRs that mutate ``forge.api.__all__``
without an entry fail review.

Versions follow ``MAJOR.MINOR`` only — no patch component, no
pre-release labels. SDK MAJOR aligns with the plugin compat boundary
(plugins may need code changes); MINOR signals additive surface
(plugins keep working, can opt into new APIs).

## 1.1 (2026-04, with forge 1.1.0-alpha.x)

Status: **stable**.

Added:

- ``ForgeAPI.require_sdk(spec: str)`` — plugin SDK version negotiation.
  Plugins call this at the top of ``register()`` to fail fast on an
  incompatible host instead of crashing with a confusing
  ``AttributeError`` when reaching for a method the host doesn't
  ship. ``spec`` is a comma-separated list of clauses
  (``">=1.1"``, ``">=1.1, <2.0"``).
- ``forge.api.SDK_VERSION`` — the version constant itself, exposed for
  plugins that want to introspect rather than constrain.
- ``ForgeAPI.add_service(capability: str, template: ServiceTemplate)``
  — register a docker-compose service keyed by capability. (Lifted
  from 1.1.0-alpha.1 release notes; the surface change is captured
  here as the first SDK_CHANGELOG entry.)

Changed:

- ``forge.fragments`` is now a namespace package (was the legacy
  monolithic ``forge/fragments.py``). All previously-public names
  (``Fragment``, ``FragmentImplSpec``, ``FRAGMENT_REGISTRY``,
  ``register_fragment``, etc.) are re-exported from the package
  root, so plugin imports of the form ``from forge.fragments import
  X`` keep working unchanged.
- ``forge.config`` is similarly a namespace package now. Same
  re-export contract — every name plugins consumed (``BackendLanguage``,
  ``ProjectConfig``, ``BACKEND_REGISTRY``, ``register_backend_language``,
  etc.) is exposed at the package root.

## 1.0 (2026-Q1, with forge 1.0.0a1 → 1.1.0-alpha.0)

Initial public SDK surface. Captures the names that landed across the
1.0.0 alpha series — recorded retroactively here so future bumps have
a baseline to diff against.

Public names:

- ``ForgeAPI`` (since 1.0.0a1)
- ``ForgeAPI.add_option`` (since 1.0.0a1)
- ``ForgeAPI.add_fragment`` (since 1.0.0a1)
- ``ForgeAPI.add_backend`` (since 1.0.0a2)
- ``ForgeAPI.add_frontend`` (since 1.0.0a4)
- ``ForgeAPI.add_command`` (since 1.0.0a4)
- ``ForgeAPI.add_emitter`` (since 1.0.0a1, **provisional**)
- ``PluginRegistration`` (since 1.0.0a1)

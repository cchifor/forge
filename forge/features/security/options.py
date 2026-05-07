"""``security.*`` options — strict CSP nginx config + CycloneDX SBOM workflow."""

from __future__ import annotations

from forge.options._registry import (
    FeatureCategory,
    Option,
    OptionType,
    register_option,
)

register_option(
    Option(
        path="security.csp",
        type=OptionType.BOOL,
        default=True,
        summary="Strict Content-Security-Policy + HSTS + X-Content-Type-Options via nginx.",
        description="""\
Drops ``infra/nginx-csp.conf`` with production-ready strict CSP (no
unsafe-inline, strict-dynamic, nonce-based script tags), HSTS, and
related defence-in-depth headers. ``include infra/nginx-csp.conf;`` from
any nginx server{} block.

BACKENDS: all (project-scoped)
DEV NOTE: relax the ``connect-src`` directive during local development
if your dev server streams from a non-default origin.""",
        category=FeatureCategory.PLATFORM,
        enables={True: ("security_csp",)},
    )
)


register_option(
    Option(
        path="security.sbom",
        type=OptionType.BOOL,
        default=False,
        summary="GitHub Actions workflow emitting a CycloneDX SBOM + pip-audit report.",
        description="""\
Adds ``.github/workflows/sbom.yml`` that generates a CycloneDX SBOM on
every push and runs pip-audit weekly. Artifacts are uploaded so SBOM
attestation and vulnerability disclosure happens as part of normal CI.

BACKENDS: python
DEPENDENCY: none runtime; CI installs cyclonedx-bom + pip-audit.""",
        category=FeatureCategory.OBSERVABILITY,
        enables={True: ("security_sbom",)},
    )
)

"""Security-posture fragments — CSP headers, SBOM emission.

Distinct from ``middleware.security_headers`` (which sets HTTP response
headers in the request path); these fragments are project-scope
(``security_csp`` ships an external CSP config) or build-time
(``security_sbom`` emits a software-bill-of-materials artifact).
"""

from __future__ import annotations

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

register_fragment(
    Fragment(
        name="security_csp",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
            BackendLanguage.NODE: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
            BackendLanguage.RUST: FragmentImplSpec(
                fragment_dir="security_csp",
                scope="project",
            ),
        },
    )
)


register_fragment(
    Fragment(
        name="security_sbom",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir="security_sbom/python",
            ),
        },
    )
)

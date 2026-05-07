"""Security-posture fragments — CSP headers, SBOM emission.

Distinct from ``middleware.security_headers`` (which sets HTTP response
headers in the request path); these fragments are project-scope
(``security_csp`` ships an external CSP config) or build-time
(``security_sbom`` emits a software-bill-of-materials artifact).
"""

from __future__ import annotations

from pathlib import Path

from forge.config import BackendLanguage
from forge.fragments._registry import register_fragment
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def _project(name: str) -> str:
    """Project-scoped fragments don't have per-language subdirs."""
    return str(_TEMPLATES / name)


# Project-scoped: same nginx config for every backend.
_CSP_IMPL = FragmentImplSpec(fragment_dir=_project("security_csp"), scope="project")
register_fragment(
    Fragment(
        name="security_csp",
        implementations={
            BackendLanguage.PYTHON: _CSP_IMPL,
            BackendLanguage.NODE: _CSP_IMPL,
            BackendLanguage.RUST: _CSP_IMPL,
        },
    )
)


register_fragment(
    Fragment(
        name="security_sbom",
        implementations={
            BackendLanguage.PYTHON: FragmentImplSpec(
                fragment_dir=_impl("security_sbom", "python"),
            ),
        },
    )
)

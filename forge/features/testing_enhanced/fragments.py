"""Testing-enhanced fragment — failure forensics + coverage registry.

Ships ``tests/utils/failure_context.py`` (pytest plugin with autouse
fixture + ``pytest_runtest_makereport`` hook) and ``tests/coverage.json``
(declarative coverage thresholds) into the generated backend.
"""

from __future__ import annotations

from pathlib import Path

from forge.api import ForgeAPI
from forge.config import BackendLanguage
from forge.fragments._spec import Fragment, FragmentImplSpec

_TEMPLATES = Path(__file__).resolve().parent / "templates"


def _impl(name: str, lang: str) -> str:
    return str(_TEMPLATES / name / lang)


def register_all(api: ForgeAPI) -> None:
    api.add_fragment(
        Fragment(
            name="testing_enhanced_python",
            implementations={
                BackendLanguage.PYTHON: FragmentImplSpec(
                    fragment_dir=_impl("testing_enhanced", "python"),
                ),
            },
        )
    )

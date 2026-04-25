"""RFC-009 service-registration loader.

Parses a fragment's ``services.yaml`` into typed
:class:`ServiceRegistration` records and exposes a renderer that
emits backend-idiomatic registration code by invoking the matching
Jinja macro under
``forge/templates/_shared/service_registration/``.

The actual application of these records into a generated backend is
done by a follow-up applier (or extended :class:`FragmentInjectionApplier`)
in a later PR — this module ships the contract and parser so plugin
authors can start writing ``services.yaml`` files immediately.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from forge.errors import ForgeError

ServiceScope = Literal["singleton", "request", "transient"]
ServiceLanguage = Literal["python", "node", "rust"]


class ServicesYamlError(ForgeError):
    """Raised when a fragment's ``services.yaml`` is malformed."""


@dataclass(frozen=True)
class ServiceRegistration:
    """One service declaration from a fragment's ``services.yaml``.

    Mirrors RFC-009. ``startup`` and ``shutdown_hook`` are optional;
    ``config_key`` may be empty when the service takes no config.
    """

    name: str
    type: str
    import_path: str
    scope: ServiceScope
    languages: tuple[ServiceLanguage, ...]
    dependencies: tuple[str, ...] = ()
    config_key: str = ""
    startup: bool = False
    shutdown_hook: str = ""

    def supports(self, language: str) -> bool:
        return language in self.languages


_VALID_SCOPES: frozenset[str] = frozenset({"singleton", "request", "transient"})
_VALID_LANGUAGES: frozenset[str] = frozenset({"python", "node", "rust"})


def load_services_yaml(path: Path) -> tuple[ServiceRegistration, ...]:
    """Parse ``services.yaml`` into typed registration records.

    Raises :class:`ServicesYamlError` with a specific message + the
    offending entry index for any shape violation.
    """
    if not path.is_file():
        return ()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    services_raw = raw.get("services") if isinstance(raw, dict) else None
    if services_raw is None:
        return ()
    if not isinstance(services_raw, list):
        raise ServicesYamlError(
            f"{path}: top-level 'services' must be a list, got {type(services_raw).__name__}",
            code="SERVICES_YAML_BAD_SHAPE",
            context={"path": str(path)},
        )

    out: list[ServiceRegistration] = []
    for idx, entry in enumerate(services_raw):
        if not isinstance(entry, dict):
            raise ServicesYamlError(
                f"{path}[{idx}]: service entry must be a mapping",
                code="SERVICES_YAML_BAD_SHAPE",
                context={"path": str(path), "index": idx},
            )
        out.append(_parse_entry(path, idx, entry))
    return tuple(out)


def _parse_entry(path: Path, idx: int, entry: dict) -> ServiceRegistration:
    for required in ("name", "type", "import_path", "scope", "languages"):
        if required not in entry:
            raise ServicesYamlError(
                f"{path}[{idx}]: missing required key {required!r}",
                code="SERVICES_YAML_MISSING_KEY",
                context={
                    "path": str(path),
                    "index": idx,
                    "missing_key": required,
                },
            )
    scope = str(entry["scope"])
    if scope not in _VALID_SCOPES:
        raise ServicesYamlError(
            f"{path}[{idx}]: scope must be one of {sorted(_VALID_SCOPES)}, got {scope!r}",
            code="SERVICES_YAML_BAD_SCOPE",
            context={"path": str(path), "index": idx, "scope": scope},
        )
    languages_raw = entry["languages"]
    if not isinstance(languages_raw, list):
        raise ServicesYamlError(
            f"{path}[{idx}]: languages must be a list of strings",
            code="SERVICES_YAML_BAD_SHAPE",
            context={"path": str(path), "index": idx},
        )
    bad = [lang for lang in languages_raw if lang not in _VALID_LANGUAGES]
    if bad:
        raise ServicesYamlError(
            f"{path}[{idx}]: unknown language(s) {bad}; valid: {sorted(_VALID_LANGUAGES)}",
            code="SERVICES_YAML_BAD_LANGUAGE",
            context={"path": str(path), "index": idx, "bad_languages": bad},
        )
    deps_raw = entry.get("dependencies", [])
    if not isinstance(deps_raw, list) or not all(isinstance(d, str) for d in deps_raw):
        raise ServicesYamlError(
            f"{path}[{idx}]: dependencies must be a list of strings",
            code="SERVICES_YAML_BAD_SHAPE",
            context={"path": str(path), "index": idx},
        )
    return ServiceRegistration(
        name=str(entry["name"]),
        type=str(entry["type"]),
        import_path=str(entry["import_path"]),
        scope=scope,  # type: ignore[arg-type]
        languages=tuple(languages_raw),
        dependencies=tuple(deps_raw),
        config_key=str(entry.get("config_key", "")),
        startup=bool(entry.get("startup", False)),
        shutdown_hook=str(entry.get("shutdown_hook", "")),
    )


def services_for_language(
    services: Iterable[ServiceRegistration],
    language: str,
) -> tuple[ServiceRegistration, ...]:
    """Filter a tuple of registrations to those targeting ``language``."""
    return tuple(s for s in services if s.supports(language))

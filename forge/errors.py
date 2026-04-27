"""Forge error hierarchy.

Lives in its own module (rather than generator.py) so docker_manager.py, cli.py,
and tests can all import it without pulling in generator's Copier dependency.

The hierarchy is intentionally narrow:

- :class:`ForgeError` — the base. Every failure forge recognises is a subclass.
- :class:`OptionsError` — option-registry and resolver-path issues
  (unknown paths, dep cycles, invalid values).
- :class:`FragmentError` — fragment layout issues (missing dirs, malformed
  ``inject.yaml``, missing dependency files).
- :class:`InjectionError` — failed AST/text injection (missing marker,
  ambiguous anchor, corrupt sentinels).
- :class:`MergeError` — three-way merge conflicts that can't be auto-resolved.
- :class:`ProvenanceError` — provenance recording / classification failures.
- :class:`PluginError` — plugin load / registration failures.

Each subclass carries a machine-readable ``code`` (e.g. ``OPTIONS_UNKNOWN_PATH``),
an optional ``hint``, and a free-form ``context`` dict. The CLI's ``--json``
envelope emits these fields verbatim so downstream agents can branch on
``code`` without regex-matching ``message``.

For backward compatibility through the 1.1 series, ``GeneratorError`` is
re-exported as an alias of :class:`ForgeError`; existing callers that do
``except GeneratorError:`` keep catching every forge failure. The alias is
scheduled for removal in 2.0.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class ForgeError(RuntimeError):
    """Base class for every failure forge raises deliberately.

    Subclasses set :attr:`DEFAULT_CODE` and any raise site may override with
    ``code=...``. ``context`` is a small dict of machine-friendly fields the
    CLI emits into the ``--json`` envelope; keep entries JSON-serialisable.
    """

    DEFAULT_CODE: ClassVar[str] = "FORGE_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        hint: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.code: str = code if code is not None else self.DEFAULT_CODE
        self.hint: str | None = hint
        self.context: dict[str, Any] = dict(context) if context is not None else {}

    def as_envelope(self) -> dict[str, Any]:
        """Serialise to the CLI ``--json`` error envelope shape."""
        envelope: dict[str, Any] = {
            "error": self.message,
            "code": self.code,
        }
        if self.hint is not None:
            envelope["hint"] = self.hint
        if self.context:
            envelope["context"] = self.context
        return envelope


class OptionsError(ForgeError):
    """Raised when option registration or resolution fails.

    Typical sites: unknown option paths, dependency cycles, invalid value
    types, conflicts between enables-maps.
    """

    DEFAULT_CODE: ClassVar[str] = "OPTIONS_ERROR"


class FragmentError(ForgeError):
    """Raised when a fragment's on-disk layout or registration is malformed.

    Typical sites: missing fragment directory, malformed ``inject.yaml``,
    missing ``deps.yaml`` / ``env.yaml`` entries, orphan ``depends_on``,
    fragment-registration collisions.
    """

    DEFAULT_CODE: ClassVar[str] = "FRAGMENT_ERROR"


class InjectionError(ForgeError):
    """Raised when the AST/text injection step fails.

    Typical sites: missing anchor/marker in target file, ambiguous anchor,
    corrupt ``FORGE:BEGIN``/``FORGE:END`` sentinel pairs.
    """

    DEFAULT_CODE: ClassVar[str] = "INJECTION_ERROR"


class MergeError(ForgeError):
    """Raised when three-way merge cannot be auto-resolved.

    Typical sites: user edited a block that the fragment also changed
    upstream; emitted ``.forge-merge`` sidecar awaiting manual resolution.
    """

    DEFAULT_CODE: ClassVar[str] = "MERGE_ERROR"


class ProvenanceError(ForgeError):
    """Raised when provenance classification or manifest IO fails.

    Typical sites: missing ``.forge/manifest.json``, corrupt provenance
    records, SHA mismatch on read-back, uninstall classification failure.
    """

    DEFAULT_CODE: ClassVar[str] = "PROVENANCE_ERROR"


class PluginError(ForgeError):
    """Raised when plugin loading or registration fails.

    Typical sites: broken entry point, plugin collides with a registered
    option/fragment, registry frozen when plugin tries to register.
    """

    DEFAULT_CODE: ClassVar[str] = "PLUGIN_ERROR"


class TemplateError(ForgeError):
    """Raised when a Copier template fails to render.

    Split from :class:`ForgeError` so ``--json`` consumers can
    distinguish template problems (user-authored Copier template bugs,
    Jinja errors) from filesystem / plugin / option problems. The
    three common raise sites are wrapped around ``copier.run_copy``:

    - :data:`TEMPLATE_RENDER_FAILED` — Copier itself raised
      ``CopierError`` (invalid copier.yml, bad template syntax,
      validator rejection, etc.).
    - :data:`TEMPLATE_JINJA_ERROR` — Jinja bubbled a ``RuntimeError``
      subclass out of the render (undefined variable in strict mode,
      recursive macro, filter crash).
    - :data:`TEMPLATE_NOT_FOUND` — the template path doesn't exist on
      disk (wheel-packaging regression, plugin shipping a missing
      ``template_dir``).
    """

    DEFAULT_CODE: ClassVar[str] = "TEMPLATE_ERROR"


class FilesystemError(ForgeError):
    """Raised when a filesystem operation fails during generation.

    Split from :class:`ForgeError` so ``--json`` consumers can tell a
    genuine IO failure (permission denied, disk full, read-only root)
    from a template bug. Currently raised from the Copier wrapper in
    :func:`forge.generator._run_copier` when the underlying ``OSError``
    surfaces; expect more sites to adopt this as other generator
    filesystem paths get the same treatment.
    """

    DEFAULT_CODE: ClassVar[str] = "FILESYSTEM_ERROR"


# ----------------------------------------------------------------------------
# Error code constants (machine-readable identifiers surfaced in --json)
# ----------------------------------------------------------------------------

# OptionsError codes
OPTIONS_UNKNOWN_PATH = "OPTIONS_UNKNOWN_PATH"
OPTIONS_INVALID_VALUE = "OPTIONS_INVALID_VALUE"
OPTIONS_DEP_CYCLE = "OPTIONS_DEP_CYCLE"
OPTIONS_MISSING_FRAGMENT = "OPTIONS_MISSING_FRAGMENT"
OPTIONS_FRAGMENT_CONFLICT = "OPTIONS_FRAGMENT_CONFLICT"

# FragmentError codes
FRAGMENT_DIR_MISSING = "FRAGMENT_DIR_MISSING"
FRAGMENT_FILES_OVERLAP = "FRAGMENT_FILES_OVERLAP"
FRAGMENT_INJECT_YAML_BAD_SHAPE = "FRAGMENT_INJECT_YAML_BAD_SHAPE"
FRAGMENT_INJECT_YAML_MISSING_KEY = "FRAGMENT_INJECT_YAML_MISSING_KEY"
FRAGMENT_INJECT_YAML_BAD_POSITION = "FRAGMENT_INJECT_YAML_BAD_POSITION"
FRAGMENT_INJECT_YAML_BAD_ZONE = "FRAGMENT_INJECT_YAML_BAD_ZONE"
FRAGMENT_DEPS_FILE_MISSING = "FRAGMENT_DEPS_FILE_MISSING"
FRAGMENT_DEPS_SECTION_MISSING = "FRAGMENT_DEPS_SECTION_MISSING"
FRAGMENT_DEP_SPEC_INVALID = "FRAGMENT_DEP_SPEC_INVALID"
FRAGMENT_ENV_INVALID = "FRAGMENT_ENV_INVALID"

# InjectionError codes
INJECTION_TARGET_MISSING = "INJECTION_TARGET_MISSING"
INJECTION_MARKER_MISSING = "INJECTION_MARKER_MISSING"
INJECTION_MARKER_AMBIGUOUS = "INJECTION_MARKER_AMBIGUOUS"
INJECTION_ANCHOR_NOT_FOUND = "INJECTION_ANCHOR_NOT_FOUND"
INJECTION_ANCHOR_AMBIGUOUS = "INJECTION_ANCHOR_AMBIGUOUS"
INJECTION_SENTINEL_CORRUPT = "INJECTION_SENTINEL_CORRUPT"

# MergeError codes
MERGE_CONFLICT = "MERGE_CONFLICT"
FILE_MERGE_CONFLICT = "FILE_MERGE_CONFLICT"

# ProvenanceError codes
PROVENANCE_MANIFEST_MISSING = "PROVENANCE_MANIFEST_MISSING"
PROVENANCE_MANIFEST_MALFORMED = "PROVENANCE_MANIFEST_MALFORMED"
PROVENANCE_UPDATE_LOCK_HELD = "PROVENANCE_UPDATE_LOCK_HELD"

# PluginError codes
PLUGIN_LOAD_FAILED = "PLUGIN_LOAD_FAILED"
PLUGIN_REGISTRATION_FAILED = "PLUGIN_REGISTRATION_FAILED"
PLUGIN_COLLISION = "PLUGIN_COLLISION"
PLUGIN_REGISTRY_FROZEN = "PLUGIN_REGISTRY_FROZEN"
PLUGIN_SDK_INCOMPATIBLE = "PLUGIN_SDK_INCOMPATIBLE"

# TemplateError codes
TEMPLATE_RENDER_FAILED = "TEMPLATE_RENDER_FAILED"
TEMPLATE_JINJA_ERROR = "TEMPLATE_JINJA_ERROR"
TEMPLATE_NOT_FOUND = "TEMPLATE_NOT_FOUND"

# FilesystemError codes
FILESYSTEM_IO_ERROR = "FILESYSTEM_IO_ERROR"


# ----------------------------------------------------------------------------
# Backward-compatibility alias — deprecated since 1.1.0, scheduled removal 2.0
# ----------------------------------------------------------------------------
#
# Historical note: ``GeneratorError = ForgeError`` was a module-level
# alias so ``except GeneratorError:`` callers kept catching every forge
# failure through the 1.x series. Epic S (1.1.0-alpha.1) flips it to a
# lazy ``__getattr__`` so reading the name emits a DeprecationWarning
# without changing the runtime semantics — it's still ``ForgeError``.
# Removal is scheduled for 2.0. New code should use ``ForgeError`` or
# one of its subclasses (``TemplateError``, ``FilesystemError``, …).


def __getattr__(name: str):
    """Lazy module-level alias for :class:`ForgeError`.

    Emits a :class:`DeprecationWarning` on read so lingering
    ``from forge.errors import GeneratorError`` sites surface as
    visible warnings in developer builds. ``tests/conftest.py``
    silences the warning for the test suite itself (the alias is
    still intentional in ``tests/test_errors.py`` regression cases).
    """
    if name == "GeneratorError":
        import warnings  # noqa: PLC0415

        warnings.warn(
            "forge.errors.GeneratorError is deprecated (since 1.1.0). "
            "Use ForgeError or a specific subclass (TemplateError, "
            "FilesystemError, InjectionError, etc.). Scheduled removal: 2.0.",
            DeprecationWarning,
            stacklevel=2,
        )
        return ForgeError
    raise AttributeError(f"module 'forge.errors' has no attribute {name!r}")

__all__ = [
    # Base + subclasses
    "ForgeError",
    "OptionsError",
    "FragmentError",
    "InjectionError",
    "MergeError",
    "ProvenanceError",
    "PluginError",
    "TemplateError",
    "FilesystemError",
    # Deprecated alias
    "GeneratorError",
    # OptionsError codes
    "OPTIONS_UNKNOWN_PATH",
    "OPTIONS_INVALID_VALUE",
    "OPTIONS_DEP_CYCLE",
    "OPTIONS_MISSING_FRAGMENT",
    "OPTIONS_FRAGMENT_CONFLICT",
    # FragmentError codes
    "FRAGMENT_DIR_MISSING",
    "FRAGMENT_FILES_OVERLAP",
    "FRAGMENT_INJECT_YAML_BAD_SHAPE",
    "FRAGMENT_INJECT_YAML_MISSING_KEY",
    "FRAGMENT_INJECT_YAML_BAD_POSITION",
    "FRAGMENT_INJECT_YAML_BAD_ZONE",
    "FRAGMENT_DEPS_FILE_MISSING",
    "FRAGMENT_DEPS_SECTION_MISSING",
    "FRAGMENT_DEP_SPEC_INVALID",
    "FRAGMENT_ENV_INVALID",
    # InjectionError codes
    "INJECTION_TARGET_MISSING",
    "INJECTION_MARKER_MISSING",
    "INJECTION_MARKER_AMBIGUOUS",
    "INJECTION_ANCHOR_NOT_FOUND",
    "INJECTION_ANCHOR_AMBIGUOUS",
    "INJECTION_SENTINEL_CORRUPT",
    # MergeError codes
    "MERGE_CONFLICT",
    "FILE_MERGE_CONFLICT",
    # ProvenanceError codes
    "PROVENANCE_MANIFEST_MISSING",
    "PROVENANCE_MANIFEST_MALFORMED",
    "PROVENANCE_UPDATE_LOCK_HELD",
    # PluginError codes
    "PLUGIN_LOAD_FAILED",
    "PLUGIN_REGISTRATION_FAILED",
    "PLUGIN_COLLISION",
    "PLUGIN_REGISTRY_FROZEN",
    "PLUGIN_SDK_INCOMPATIBLE",
    # TemplateError codes
    "TEMPLATE_RENDER_FAILED",
    "TEMPLATE_JINJA_ERROR",
    "TEMPLATE_NOT_FOUND",
    # FilesystemError codes
    "FILESYSTEM_IO_ERROR",
]

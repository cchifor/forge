# weld-* SDK stubs for matrix CI

These are minimal namespace-package stubs that satisfy ``uv sync`` +
``ty check`` for forge-generated Python services in the matrix verify
lane (and the e2e Python lane).

**Why they exist**

The Python service template's ``pyproject.toml.jinja`` lists
``weld-{auth,core,fastapi,observability,http-client,events}`` as
runtime dependencies and ``[tool.uv.sources]`` points each at
``../../sdks/weld-<name>/`` — the in-platform-monorepo SDK trees. The
matrix CI runner has no platform sibling tree, so the real weld-*
sources are unavailable and ``uv sync`` fails with
``Distribution not found at: file:///.../sdks/weld-auth``.

These stubs let the lane B verify (``uv sync`` + ``ruff check`` +
``ruff format`` + ``ty check`` + ``pytest``) run end-to-end without
the real weld monorepo. They expose the same import surface as
``weld-*`` so ``from weld.core.persistence.db.aio import
AsyncDatabase`` resolves; the bodies are minimal (``pass`` or stub
classes) since matrix verify cares about structural integrity, not
runtime behavior.

**How they get injected**

``tests/matrix/runner.py::_inject_weld_stubs`` walks this directory
and ``shutil.copytree``s every ``weld-<name>/`` into
``<project_root>/sdks/`` after ``generate()`` and before
``toolchain.verify()``. Same hook in ``tests/e2e/test_full_generation.py``.

**Maintenance**

If the templates start importing a new ``weld.<name>.<symbol>``, add
the symbol to the matching ``src/weld/<name>/`` module here. The
exported surface is intentionally narrow — only the names forge
templates actually import.

"""Path-exclusion predicates shared between FR2 (matrix roundtrip) and
golden-snapshot tests.

Two consecutive generates of the same scenario must produce byte-identical
trees once these paths are filtered. The filtered families fall into three
buckets:

* **VCS / generator internals.** ``.git/`` differs across two ``git init``
  invocations (different SHA-1 of the empty tree). ``.copier-answers.yml``
  carries Copier's ``_commit`` / ``_src_path`` which drift across re-runs.
* **Python tool caches.** ``__pycache__/`` + ``*.pyc`` embed timestamps;
  ``.ruff_cache/`` / ``.pytest_cache/`` / ``.mypy_cache/`` carry tool-state
  hashes; ``.venv/`` is a synthesized virtualenv whose internals vary
  across uv versions and platform tooling.
* **Frontend/Rust build outputs.** ``node_modules/`` is the npm-install
  resolution order + Prisma's runtime client generation. ``.svelte-kit/``
  is regenerated on every ``npm run build``. ``build/`` / ``dist/`` are
  bundle outputs whose source-map paths embed absolute paths. ``target/``
  is the Cargo workspace's shared build artifact tree.

Deliberate omissions (kept visible to FR2 even when ignored by golden
snapshots): ``package-lock.json`` / ``auto-imports.d.ts`` /
``/api/generated/``. These ARE deterministic on a single CI host (frozen
lockfiles, deterministic codegen) and an FR2 difference in them indicates
a real round-trip bug — exactly what roundtrip should catch. Golden
snapshots treat them as host-asymmetric noise instead because the snapshot
host varies across contributors.
"""

from __future__ import annotations


def is_generated_artefact(rel: str) -> bool:
    """Return True if ``rel`` (a POSIX relative path) is non-deterministic
    across two consecutive generates on the same host."""
    # VCS internals — empty-tree SHAs vary across git init runs.
    if rel == ".git" or rel.startswith(".git/") or "/.git/" in rel:
        return True
    # NOTE — .copier-answers.yml drift IS host-asymmetric (``_commit`` and
    # ``_src_path`` differ across re-renders), but golden snapshots
    # currently INCLUDE these files in their baselines. The matrix
    # runner's _diff_project_trees_normalized keeps an inline exclusion
    # for this file; the shared helper does not.
    # Python bytecode (timestamp-dependent) + tool caches.
    if "/__pycache__/" in rel or rel.startswith("__pycache__/"):
        return True
    if rel.endswith(".pyc"):
        return True
    for cache in ("/.ruff_cache/", "/.pytest_cache/", "/.mypy_cache/", "/.venv/"):
        if cache in rel:
            return True
    for cache_root in (".ruff_cache/", ".pytest_cache/", ".mypy_cache/", ".venv/"):
        if rel.startswith(cache_root):
            return True
    # Node — npm install resolution + Prisma codegen are unstable across
    # runs even with frozen lockfiles (timestamps, internal hashes).
    if "/node_modules/" in rel or rel.startswith("node_modules/"):
        return True
    # SvelteKit generated output — recreated on every `npm run build`.
    if "/.svelte-kit/" in rel or rel.startswith(".svelte-kit/"):
        return True
    # Frontend bundle output — source maps embed absolute paths.
    if "/build/" in rel or "/dist/" in rel:
        return True
    # Cargo workspace target/ tree — only present if a prior build leaked.
    if "/target/" in rel or rel.startswith("target/"):
        return True
    return False

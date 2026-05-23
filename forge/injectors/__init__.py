"""Language-aware injection backends for forge fragments.

Each injector handles a specific file type:

    forge.injectors.python_ast  — LibCST-based Python injection
    (TypeScript ts-morph injector is a follow-up for 1.0.0a2)

The injector dispatcher in :func:`forge.appliers.injection._dispatch_injector`
routes files by extension to the right backend via the pluggable
:class:`forge.injectors._registry.ApplierRegistry` (Pillar A.1, SDK 1.2).
Built-in suffixes seed at import time; plugins register new file types
via :meth:`forge.api.ForgeAPI.add_injector`. Text-marker injection
remains the wildcard fallback for file types we haven't migrated yet
(Rust, YAML, TOML).
"""

"""Language-aware injection backends for forge fragments.

Each injector handles a specific file type:

    forge.injectors.python_ast  — LibCST-based Python injection
    (TypeScript ts-morph injector is a follow-up for 1.0.0a2)

The injector dispatcher in ``forge.feature_injector`` routes files by
extension to the right backend. Text-marker injection remains the
fallback for file types we haven't migrated yet (Rust, YAML, TOML).
"""

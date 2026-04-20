"""Code-generation subsystem for forge 1.0's schema-first core.

Phase 1 replaces hand-maintained type mirrors (domain enums, agentic-UI
protocol, canvas component contracts) with generators driven by a single
source of truth. Each submodule handles one target:

    forge.codegen.enums           — YAML enum registry → Python / Node / Rust / TS / Dart
    forge.codegen.ui_protocol     — JSON Schema → TS / Dart / Pydantic (Phase 1.1)
    forge.codegen.canvas_contract — per-component props schemas (Phase 1.2)

This module intentionally stays small — it's a namespace, not a pipeline.
Individual emitters are free-standing and can be invoked from the CLI,
from plugins, or as imported library code.
"""

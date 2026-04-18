"""Fragment smoke tests for `agent` (pydantic-ai LLM loop).

Minimal: confirms llm_runner module imports and its run-generator is
callable. The full LLM flow isn't tested here — that requires network
access or a mock-provider harness (out of scope for smoke).
"""

from __future__ import annotations


def test_llm_runner_imports_and_exposes_runner() -> None:
    from app.agents import llm_runner

    # The runner-dispatch module prefers llm_runner.run_agent if present.
    assert callable(getattr(llm_runner, "run_agent", None))

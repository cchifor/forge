"""``agent.*`` and ``llm.*`` features — LLM agent platform.

Wave C of the features-reorganization refactor. Owns the agent triple
(agent_streaming → agent_tools → agent), the agent.mode layer
discriminator, and the LLM provider port + adapters
(llm_port + llm_openai/anthropic/ollama/bedrock).

Cross-feature edge: ``agent_streaming`` depends on
``conversation_persistence`` (in ``forge.features.conversation``).
The dependency is by fragment name; the resolver freezes the registry
after every feature has registered, so the import order doesn't matter.
"""

from __future__ import annotations

from forge.features.agent import (  # noqa: F401, E402
    fragments,
    options,
)

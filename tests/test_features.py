"""Tests for the feature registry and FeatureConfig parsing."""

from __future__ import annotations

import pytest

from forge.config import BackendLanguage
from forge.features import (
    FEATURE_REGISTRY,
    FeatureConfig,
    FeatureSpec,
    FragmentImplSpec,
    fragments_root,
    register,
)


class TestFeatureConfigFromDict:
    def test_true_shorthand(self) -> None:
        cfg = FeatureConfig.from_dict(True)
        assert cfg.enabled is True
        assert cfg.options == {}

    def test_false_shorthand(self) -> None:
        cfg = FeatureConfig.from_dict(False)
        assert cfg.enabled is False

    def test_none_is_disabled(self) -> None:
        cfg = FeatureConfig.from_dict(None)
        assert cfg.enabled is False

    def test_full_dict(self) -> None:
        cfg = FeatureConfig.from_dict({"enabled": True, "options": {"ttl": 60}})
        assert cfg.enabled is True
        assert cfg.options == {"ttl": 60}

    def test_enabled_missing_defaults_false(self) -> None:
        cfg = FeatureConfig.from_dict({"options": {"x": 1}})
        assert cfg.enabled is False
        assert cfg.options == {"x": 1}

    def test_rejects_scalar(self) -> None:
        with pytest.raises(ValueError, match="must be bool or dict"):
            FeatureConfig.from_dict("enabled")

    def test_rejects_non_dict_options(self) -> None:
        with pytest.raises(ValueError, match="options must be a dict"):
            FeatureConfig.from_dict({"enabled": True, "options": ["nope"]})

    def test_roundtrip(self) -> None:
        original = {"enabled": True, "options": {"a": 1, "b": "two"}}
        assert FeatureConfig.from_dict(original).to_dict() == original


class TestRegistryIntegrity:
    def test_correlation_id_registered(self) -> None:
        assert "correlation_id" in FEATURE_REGISTRY
        spec = FEATURE_REGISTRY["correlation_id"]
        assert spec.always_on is True
        assert BackendLanguage.PYTHON in spec.implementations

    def test_rate_limit_registered(self) -> None:
        spec = FEATURE_REGISTRY["rate_limit"]
        assert spec.default_enabled is True
        assert spec.order == 50
        assert BackendLanguage.PYTHON in spec.implementations
        assert BackendLanguage.NODE in spec.implementations
        # Node fragment declares @fastify/rate-limit as a dep.
        assert any("@fastify/rate-limit" in d for d in spec.implementations[BackendLanguage.NODE].dependencies)

    def test_observability_registered(self) -> None:
        spec = FEATURE_REGISTRY["observability"]
        assert spec.default_enabled is False
        py_impl = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("logfire") for d in py_impl.dependencies)
        env_keys = {k for k, _ in py_impl.env_vars}
        assert "LOGFIRE_TOKEN" in env_keys

    def test_agents_md_project_scope(self) -> None:
        spec = FEATURE_REGISTRY["agents_md"]
        for lang_impl in spec.implementations.values():
            assert lang_impl.scope == "project"

    def test_rate_limit_covers_all_backends(self) -> None:
        spec = FEATURE_REGISTRY["rate_limit"]
        for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
            assert lang in spec.implementations, f"rate_limit missing {lang.value}"

    def test_enhanced_health_is_beta(self) -> None:
        spec = FEATURE_REGISTRY["enhanced_health"]
        assert spec.stability == "beta"
        assert spec.default_enabled is False
        py = spec.implementations[BackendLanguage.PYTHON]
        env_keys = {k for k, _ in py.env_vars}
        assert "REDIS_URL" in env_keys and "KEYCLOAK_HEALTH_URL" in env_keys

    def test_agent_tools_is_experimental(self) -> None:
        spec = FEATURE_REGISTRY["agent_tools"]
        assert spec.stability == "experimental"
        assert spec.default_enabled is False

    def test_conversation_persistence_registered(self) -> None:
        spec = FEATURE_REGISTRY["conversation_persistence"]
        assert spec.stability == "beta"
        assert spec.default_enabled is False
        assert BackendLanguage.PYTHON in spec.implementations

    def test_agent_streaming_depends_on_conversation_persistence(self) -> None:
        spec = FEATURE_REGISTRY["agent_streaming"]
        assert spec.stability == "experimental"
        assert spec.default_enabled is False
        assert "conversation_persistence" in spec.depends_on

    def test_agent_depends_on_streaming_and_tools(self) -> None:
        spec = FEATURE_REGISTRY["agent"]
        assert spec.stability == "experimental"
        assert spec.default_enabled is False
        assert "agent_streaming" in spec.depends_on
        assert "agent_tools" in spec.depends_on
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("pydantic-ai") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "LLM_PROVIDER" in env_keys
        assert "ANTHROPIC_API_KEY" in env_keys

    def test_file_upload_depends_on_conversation_persistence(self) -> None:
        spec = FEATURE_REGISTRY["file_upload"]
        assert spec.stability == "beta"
        assert spec.default_enabled is False
        assert "conversation_persistence" in spec.depends_on
        py = spec.implementations[BackendLanguage.PYTHON]
        env_keys = {k for k, _ in py.env_vars}
        assert "UPLOAD_DIR" in env_keys
        assert "MAX_UPLOAD_SIZE" in env_keys
        assert any(d.startswith("python-multipart") for d in py.dependencies)

    def test_rag_pipeline_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_pipeline"]
        assert spec.stability == "experimental"
        assert spec.default_enabled is False
        assert "conversation_persistence" in spec.depends_on
        assert "postgres-pgvector" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("pgvector") for d in py.dependencies)
        assert any(d.startswith("openai") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "EMBEDDING_MODEL" in env_keys
        assert "EMBEDDING_DIM" in env_keys
        assert "RAG_TOP_K" in env_keys

    def test_enhanced_health_covers_all_backends(self) -> None:
        spec = FEATURE_REGISTRY["enhanced_health"]
        for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
            assert lang in spec.implementations, f"enhanced_health missing {lang.value}"

    def test_response_cache_registered(self) -> None:
        spec = FEATURE_REGISTRY["response_cache"]
        assert "redis" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("fastapi-cache2") for d in py.dependencies)
        node = spec.implementations[BackendLanguage.NODE]
        assert any("@fastify/caching" in d for d in node.dependencies)

    def test_background_tasks_registered(self) -> None:
        spec = FEATURE_REGISTRY["background_tasks"]
        assert "redis" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("taskiq") and not d.startswith("taskiq-") for d in py.dependencies)
        assert any(d.startswith("taskiq-redis") for d in py.dependencies)
        node = spec.implementations[BackendLanguage.NODE]
        assert any(d.startswith("bullmq") for d in node.dependencies)

    def test_observability_covers_all_backends(self) -> None:
        spec = FEATURE_REGISTRY["observability"]
        for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
            assert lang in spec.implementations
        node = spec.implementations[BackendLanguage.NODE]
        assert any("@opentelemetry/sdk-node" in d for d in node.dependencies)

    def test_rag_qdrant_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_qdrant"]
        assert "rag_pipeline" in spec.depends_on
        assert "qdrant" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("qdrant-client") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "QDRANT_URL" in env_keys

    def test_rag_pipeline_has_pdf_support(self) -> None:
        py = FEATURE_REGISTRY["rag_pipeline"].implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("pymupdf") for d in py.dependencies)

    def test_cli_commands_registered(self) -> None:
        spec = FEATURE_REGISTRY["cli_commands"]
        assert spec.stability == "beta"
        assert BackendLanguage.PYTHON in spec.implementations

    def test_webhooks_covers_python_and_node(self) -> None:
        spec = FEATURE_REGISTRY["webhooks"]
        assert BackendLanguage.PYTHON in spec.implementations
        assert BackendLanguage.NODE in spec.implementations
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("httpx") for d in py.dependencies)

    def test_admin_panel_registered(self) -> None:
        spec = FEATURE_REGISTRY["admin_panel"]
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("sqladmin") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "ADMIN_PANEL_MODE" in env_keys

    def test_rag_postgresql_no_pgvector_dep(self) -> None:
        spec = FEATURE_REGISTRY["rag_postgresql"]
        assert "rag_pipeline" in spec.depends_on
        py = spec.implementations[BackendLanguage.PYTHON]
        # Deliberately does NOT ship pgvector — that's the whole point.
        assert not any(d.startswith("pgvector") for d in py.dependencies)

    def test_rag_chroma_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_chroma"]
        assert "rag_pipeline" in spec.depends_on
        assert "chroma" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("chromadb") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "CHROMA_URL" in env_keys

    def test_rag_reranking_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_reranking"]
        assert "rag_pipeline" in spec.depends_on
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("cohere") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "RERANKER_PROVIDER" in env_keys

    def test_rag_voyage_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_embeddings_voyage"]
        assert "rag_pipeline" in spec.depends_on
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("voyageai") for d in py.dependencies)
        env_keys = {k for k, _ in py.env_vars}
        assert "VOYAGE_API_KEY" in env_keys

    def test_rag_milvus_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_milvus"]
        assert "milvus" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("pymilvus") for d in py.dependencies)

    def test_rag_weaviate_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_weaviate"]
        assert "weaviate" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("weaviate-client") for d in py.dependencies)

    def test_rag_pinecone_registered(self) -> None:
        spec = FEATURE_REGISTRY["rag_pinecone"]
        assert "pinecone" in spec.capabilities
        py = spec.implementations[BackendLanguage.PYTHON]
        assert any(d.startswith("pinecone") for d in py.dependencies)

    def test_observability_rust_has_full_deps(self) -> None:
        spec = FEATURE_REGISTRY["observability"]
        rust = spec.implementations[BackendLanguage.RUST]
        assert any("opentelemetry-otlp" in d for d in rust.dependencies)
        assert any(d.startswith("tracing-opentelemetry") for d in rust.dependencies)

    def test_webhooks_covers_all_three_backends(self) -> None:
        spec = FEATURE_REGISTRY["webhooks"]
        for lang in (BackendLanguage.PYTHON, BackendLanguage.NODE, BackendLanguage.RUST):
            assert lang in spec.implementations, f"webhooks missing {lang.value}"

    def test_background_tasks_rust_uses_apalis(self) -> None:
        spec = FEATURE_REGISTRY["background_tasks"]
        rust = spec.implementations[BackendLanguage.RUST]
        assert any(d.startswith("apalis@") for d in rust.dependencies)
        assert any(d.startswith("apalis-redis") for d in rust.dependencies)

    def test_rag_sync_tasks_depends_on_rag_and_bg(self) -> None:
        spec = FEATURE_REGISTRY["rag_sync_tasks"]
        assert "rag_pipeline" in spec.depends_on
        assert "background_tasks" in spec.depends_on

    def test_middleware_order_ascending(self) -> None:
        # Convention: rate_limit < security_headers < correlation_id so
        # Starlette stack ends up innermost-to-outermost in that order.
        rl = FEATURE_REGISTRY["rate_limit"].order
        sh = FEATURE_REGISTRY["security_headers"].order
        ci = FEATURE_REGISTRY["correlation_id"].order
        assert rl < sh < ci

    def test_every_impl_fragment_dir_exists(self) -> None:
        root = fragments_root()
        for key, spec in FEATURE_REGISTRY.items():
            for lang, impl in spec.implementations.items():
                path = root / impl.fragment_dir
                assert path.is_dir(), (
                    f"Feature '{key}' ({lang.value}) declares "
                    f"fragment_dir='{impl.fragment_dir}' but {path} does not exist"
                )

    def test_register_duplicate_raises(self) -> None:
        duplicate = FeatureSpec(
            key="correlation_id",
            display_label="duplicate",
            cli_flag="--x",
            implementations={},
        )
        with pytest.raises(ValueError, match="already registered"):
            register(duplicate)

    def test_supports_language(self) -> None:
        spec = FeatureSpec(
            key="temp",
            display_label="t",
            cli_flag="--temp",
            implementations={BackendLanguage.RUST: FragmentImplSpec(fragment_dir="x")},
        )
        assert spec.supports(BackendLanguage.RUST) is True
        assert spec.supports(BackendLanguage.PYTHON) is False

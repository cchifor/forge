"""Theme 5-C1 — typed config model tests.

Covers:

* Per-layer discriminated unions accept every registered mode value
  and reject unregistered ones.
* ``from_legacy_options`` round-trips against ``to_legacy_options``
  for every layer-mode combination + non-layer-key pass-through.
* Pydantic ValidationError surfaces with a useful field path when the
  legacy dict carries a typo.
* The default ``TypedConfig`` matches the defaults the registered
  Options declare — drift here would mean the typed model and the
  legacy dict disagree on what "user supplied nothing" means.
"""

from __future__ import annotations

import itertools

import pytest

from forge.config.typed_config import (
    AgentLlmOnly,
    AgentMultiAgent,
    AgentNone,
    AgentToolCalling,
    BackendGenerate,
    BackendNone,
    DatabaseGenerate,
    DatabaseNone,
    FrontendExternal,
    FrontendGenerate,
    FrontendNone,
    TypedConfig,
    ValidationError,
    from_legacy_options,
    to_legacy_options,
)


# -- Discriminated-union shape -------------------------------------------------


class TestBackendDiscriminator:
    def test_generate(self):
        cfg = TypedConfig(backend={"mode": "generate"})
        assert isinstance(cfg.backend, BackendGenerate)
        assert cfg.backend.mode == "generate"

    def test_none(self):
        cfg = TypedConfig(backend={"mode": "none"})
        assert isinstance(cfg.backend, BackendNone)
        assert cfg.backend.mode == "none"

    def test_invalid_mode(self):
        with pytest.raises(ValidationError) as excinfo:
            TypedConfig(backend={"mode": "geneate"})
        assert "backend" in str(excinfo.value)


class TestFrontendDiscriminator:
    def test_generate_default_api_target(self):
        cfg = TypedConfig(frontend={"mode": "generate"})
        assert isinstance(cfg.frontend, FrontendGenerate)
        assert cfg.frontend.api_target_type == "local"
        assert cfg.frontend.api_target_url == ""

    def test_external(self):
        cfg = TypedConfig(
            frontend={
                "mode": "external",
                "api_target_type": "external",
                "api_target_url": "https://api.example.com",
            }
        )
        assert isinstance(cfg.frontend, FrontendExternal)
        assert cfg.frontend.api_target_url == "https://api.example.com"

    def test_none(self):
        cfg = TypedConfig(frontend={"mode": "none"})
        assert isinstance(cfg.frontend, FrontendNone)

    def test_invalid_api_target_type(self):
        with pytest.raises(ValidationError):
            TypedConfig(frontend={"mode": "generate", "api_target_type": "weird"})


class TestDatabaseDiscriminator:
    def test_generate_default_engine(self):
        cfg = TypedConfig(database={"mode": "generate"})
        assert isinstance(cfg.database, DatabaseGenerate)
        assert cfg.database.engine == "postgres"

    def test_none(self):
        cfg = TypedConfig(database={"mode": "none"})
        assert isinstance(cfg.database, DatabaseNone)

    def test_invalid_engine(self):
        with pytest.raises(ValidationError):
            TypedConfig(database={"mode": "generate", "engine": "mysql"})


class TestAgentDiscriminator:
    @pytest.mark.parametrize(
        "mode,cls",
        [
            ("none", AgentNone),
            ("llm_only", AgentLlmOnly),
            ("tool_calling", AgentToolCalling),
            ("multi_agent", AgentMultiAgent),
        ],
    )
    def test_each_mode(self, mode: str, cls: type):
        cfg = TypedConfig(agent={"mode": mode})
        assert isinstance(cfg.agent, cls)
        assert cfg.agent.mode == mode

    def test_invalid_mode(self):
        with pytest.raises(ValidationError):
            TypedConfig(agent={"mode": "nope"})


# -- Defaults align with the registry -----------------------------------------


class TestDefaults:
    def test_empty_typedconfig_matches_registered_defaults(self):
        """``TypedConfig()`` with no kwargs picks up the registered
        defaults — same as ``options.get(path, default)`` returning the
        default. Drift here means the typed model and the dict disagree
        on the empty-options shape, which would break the C3 cutover."""
        from forge.options import OPTION_REGISTRY  # noqa: PLC0415

        cfg = TypedConfig()
        assert cfg.backend.mode == OPTION_REGISTRY["backend.mode"].default
        assert cfg.frontend.mode == OPTION_REGISTRY["frontend.mode"].default
        assert cfg.database.mode == OPTION_REGISTRY["database.mode"].default
        assert cfg.agent.mode == OPTION_REGISTRY["agent.mode"].default
        # Frontend api_target fields default through the generate sub-model.
        assert isinstance(cfg.frontend, FrontendGenerate)
        assert cfg.frontend.api_target_type == OPTION_REGISTRY["frontend.api_target.type"].default
        assert cfg.frontend.api_target_url == OPTION_REGISTRY["frontend.api_target.url"].default
        assert isinstance(cfg.database, DatabaseGenerate)
        assert cfg.database.engine == OPTION_REGISTRY["database.engine"].default


# -- from_legacy_options + round-trip -----------------------------------------


class TestFromLegacyOptions:
    def test_empty_dict(self):
        cfg = from_legacy_options({})
        assert isinstance(cfg.backend, BackendGenerate)
        assert isinstance(cfg.frontend, FrontendGenerate)
        assert isinstance(cfg.database, DatabaseGenerate)
        assert isinstance(cfg.agent, AgentNone)
        assert cfg.other == {}

    def test_rewrites_legacy_alias(self):
        """``frontend.api_target_url`` (Phase A flat path) routes onto
        the canonical ``frontend.api_target.url`` field."""
        cfg = from_legacy_options(
            {
                "frontend.api_target_url": "https://api.example.com",
            }
        )
        assert isinstance(cfg.frontend, FrontendGenerate)
        assert cfg.frontend.api_target_url == "https://api.example.com"

    def test_alias_table_is_the_registry_index(self):
        """Initiative #7 — typed_config's alias projection comes from
        ``OPTION_ALIAS_INDEX``, not a local literal. Pre-#7 the two
        tables could drift silently (typed_config would shrug a typo'd
        alias into the ``other`` bag, the resolver would error
        downstream). Now the registry is the single source of truth.

        We assert by registering a new alias and confirming
        ``from_legacy_options`` picks it up without any change to
        typed_config.py."""
        from forge.options import (  # noqa: PLC0415
            OPTION_ALIAS_INDEX,
            OPTION_REGISTRY,
            FeatureCategory,
            Option,
            OptionType,
            register_option,
        )

        opt_path = "test_init7.dynamic"
        alias_path = "test_init7.dynamic_alias"
        # Best-effort cleanup if a previous run left state behind.
        OPTION_REGISTRY.pop(opt_path, None)
        OPTION_ALIAS_INDEX.pop(alias_path, None)
        register_option(
            Option(
                path=opt_path,
                type=OptionType.BOOL,
                default=False,
                summary="alias dedup smoke",
                description="proves typed_config reads OPTION_ALIAS_INDEX",
                category=FeatureCategory.PLATFORM,
                aliases=(alias_path,),
                deprecated_since="1.2.0",
            )
        )
        try:
            cfg = from_legacy_options({alias_path: True})
            # The alias was rewritten to the canonical path before
            # landing in ``other`` — proving the registry index is the
            # source of truth.
            assert cfg.other.get(opt_path) is True
            assert alias_path not in cfg.other
        finally:
            OPTION_REGISTRY.pop(opt_path, None)
            OPTION_ALIAS_INDEX.pop(alias_path, None)

    def test_passes_through_non_layer_options(self):
        cfg = from_legacy_options(
            {
                "rag.backend": "qdrant",
                "agent.streaming": True,
                "rag.top_k": 7,
            }
        )
        assert cfg.other == {
            "rag.backend": "qdrant",
            "agent.streaming": True,
            "rag.top_k": 7,
        }

    def test_typo_raises_validation_error(self):
        """The headline C1 win: a typo'd mode value fails loudly with
        a Pydantic ValidationError naming the field path."""
        with pytest.raises(ValidationError) as excinfo:
            from_legacy_options({"backend.mode": "geneate"})  # typo
        # Pydantic 2 names the discriminator + each variant in the
        # error; we just assert the layer name is in the message.
        msg = str(excinfo.value)
        assert "backend" in msg

    def test_database_engine_alone_implies_generate_mode(self):
        """A legacy dict carrying ``database.engine`` without an
        explicit ``database.mode`` is the historical default state
        (``generate`` is the implicit mode). The converter mirrors
        that — supplying engine alone keeps the generate sub-model."""
        cfg = from_legacy_options({"database.engine": "postgres"})
        assert isinstance(cfg.database, DatabaseGenerate)
        assert cfg.database.engine == "postgres"

    def test_frontend_url_alone_implies_generate_mode(self):
        cfg = from_legacy_options(
            {"frontend.api_target.url": "https://api.example.com"}
        )
        assert isinstance(cfg.frontend, FrontendGenerate)
        assert cfg.frontend.api_target_url == "https://api.example.com"

    def test_database_mode_none_drops_persisted_engine_default(self):
        """Regression (#260): a ``database.mode=none`` manifest also carries
        the registry's blanket ``database.engine=postgres`` default. The
        forward converter must drop the mode-inapplicable ``engine`` (it
        only exists on ``DatabaseGenerate``) instead of forwarding it into
        ``DatabaseNone``, whose ``extra="forbid"`` rejects it.

        Mirrors ``to_legacy_options``, which already omits ``engine`` for
        the none variant.
        """
        cfg = from_legacy_options(
            {"database.mode": "none", "database.engine": "postgres"}
        )
        assert isinstance(cfg.database, DatabaseNone)
        assert cfg.database.mode == "none"

    def test_frontend_mode_none_drops_persisted_api_target_defaults(self):
        """Sibling of #260: a ``frontend.mode=none`` manifest carries the
        registry's blanket ``frontend.api_target.*`` defaults. They live
        only on the generate/external variants; the converter must drop
        them rather than trip ``FrontendNone``'s ``extra="forbid"``.
        """
        cfg = from_legacy_options(
            {
                "frontend.mode": "none",
                "frontend.api_target.type": "local",
                "frontend.api_target.url": "",
            }
        )
        assert isinstance(cfg.frontend, FrontendNone)
        assert cfg.frontend.mode == "none"


# -- to_legacy_options round-trip ---------------------------------------------


class TestToLegacyOptionsRoundTrip:
    """For every combination of layer-mode values, converting through
    the typed model and back yields a dict that is semantically equal
    to the original (after default-fill-in)."""

    # Permutations the round-trip suite walks. Excludes the
    # ``multi_agent`` agent value because no other test path validates
    # it end-to-end; the discriminator-shape tests above cover it
    # individually.
    _BACKEND_MODES = ("generate", "none")
    _FRONTEND_MODES = ("generate", "external", "none")
    _DATABASE_MODES = ("generate", "none")
    _AGENT_MODES = ("none", "llm_only", "tool_calling")

    @pytest.mark.parametrize(
        "backend,frontend,database,agent",
        list(
            itertools.product(
                _BACKEND_MODES, _FRONTEND_MODES, _DATABASE_MODES, _AGENT_MODES
            )
        ),
    )
    def test_round_trip(
        self, backend: str, frontend: str, database: str, agent: str
    ):
        seed: dict[str, object] = {
            "backend.mode": backend,
            "frontend.mode": frontend,
            "database.mode": database,
            "agent.mode": agent,
        }
        cfg = from_legacy_options(seed)
        emitted = to_legacy_options(cfg)
        # The emitted dict must agree with the seed on every key the
        # seed supplied; it may carry additional derived defaults
        # (``database.engine`` for generate, api_target fields for
        # generate/external frontend) which is fine.
        for k, v in seed.items():
            assert emitted[k] == v
        # And a re-conversion must yield the same typed model.
        cfg2 = from_legacy_options(emitted)
        assert cfg2 == cfg

    def test_other_keys_survive_round_trip(self):
        seed = {
            "backend.mode": "generate",
            "rag.backend": "qdrant",
            "agent.streaming": True,
            "rag.top_k": 7,
            "platform.admin": False,
        }
        cfg = from_legacy_options(seed)
        emitted = to_legacy_options(cfg)
        for k, v in seed.items():
            assert emitted[k] == v


# -- Immutability --------------------------------------------------------------


class TestImmutability:
    """``TypedConfig`` and its sub-models are frozen — mutation must
    raise. The legacy dict permits in-place mutation but the audit
    found no consumer that relies on it; freezing the typed surface
    prevents a future regression where someone reaches for
    ``cfg.backend.mode = "none"`` instead of constructing a new model."""

    def test_root_is_frozen(self):
        cfg = TypedConfig()
        with pytest.raises(ValidationError):
            cfg.backend = BackendNone()  # type: ignore[misc]

    def test_submodel_is_frozen(self):
        cfg = TypedConfig(backend={"mode": "generate"})
        with pytest.raises(ValidationError):
            cfg.backend.mode = "none"  # type: ignore[misc]

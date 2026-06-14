"""Unknown top-level ``--config`` keys must fail fast, not silently generate.

A typo like ``fronend:`` used to be dropped on the floor — the project
generated without that section and forge exited 0, so the mistake only
surfaced much later (a confidently-wrong project). ``_build_config`` now
rejects unknown top-level keys with a close-match hint.
"""

from __future__ import annotations

import pytest

from forge.cli.builder import (
    _KNOWN_TOP_LEVEL_CONFIG_KEYS,
    _build_config,
    _reject_unknown_top_level_keys,
)
from forge.cli.parser import _build_parser


def _args():
    return _build_parser().parse_args([])


def test_typo_key_rejected_with_close_match():
    with pytest.raises(ValueError, match="did you mean 'frontend'"):
        _reject_unknown_top_level_keys({"fronend": {"framework": "vue"}})


def test_unknown_key_lists_every_valid_key():
    with pytest.raises(ValueError) as exc:
        _reject_unknown_top_level_keys({"totally_made_up": 1})
    msg = str(exc.value)
    assert "totally_made_up" in msg
    for key in _KNOWN_TOP_LEVEL_CONFIG_KEYS:
        assert key in msg, f"valid key {key!r} not offered in the error"


def test_multiple_unknown_keys_all_reported():
    with pytest.raises(ValueError) as exc:
        _reject_unknown_top_level_keys({"fronend": 1, "bakends": 2})
    msg = str(exc.value)
    assert "fronend" in msg and "bakends" in msg


def test_all_known_keys_accepted():
    # Inspecting keys only — values are irrelevant to the guard.
    _reject_unknown_top_level_keys({k: {} for k in _KNOWN_TOP_LEVEL_CONFIG_KEYS})


def test_empty_config_accepted():
    _reject_unknown_top_level_keys({})


def test_non_dict_config_is_left_for_downstream():
    # A top-level YAML list isn't this guard's job — don't crash on it.
    _reject_unknown_top_level_keys([1, 2, 3])  # type: ignore[arg-type]


def test_build_config_rejects_typo_end_to_end():
    # Wired into the real build path, ahead of the platform-preset merge.
    with pytest.raises(ValueError, match="did you mean 'frontend'"):
        _build_config(_args(), {"fronend": {"framework": "vue"}})


def test_build_config_accepts_valid_config():
    config = _build_config(_args(), {"project_name": "demo"})
    assert config.project_name == "demo"

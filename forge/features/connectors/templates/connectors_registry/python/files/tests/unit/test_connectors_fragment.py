"""Fragment unit tests for the vendored connector framework (weld-free).

Runs inside the generated project — imports ``app.connectors.*`` only,
never ``weld``. Covers: registry register/build + config validation, a
builtin round-trip through the sync runner (sample → filesystem), and the
SQLConnector ``auto_create_table`` opt-in gate (default off).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.connectors import (
    ConnectorRegistry,
    ConnectorRegistryError,
    SyncRunner,
)
from app.connectors.builtin.fs import FilesystemConnector
from app.connectors.builtin.sample import SampleConnector
from app.connectors.builtin.sql import SQLConfig
from app.connectors.registry import build_default_connector_registry


def test_registry_register_and_get() -> None:
    reg = ConnectorRegistry()
    reg.register(SampleConnector)
    assert reg.names() == ["sample"]
    assert reg.get("sample") is SampleConnector
    with pytest.raises(ConnectorRegistryError):
        reg.get("does-not-exist")


def test_registry_build_validates_config() -> None:
    reg = ConnectorRegistry()
    reg.register(SampleConnector)
    conn = reg.build("sample", config={"record_count": 3, "batch_size": 2})
    assert isinstance(conn, SampleConnector)
    # An invalid config raises a registry error, not a bare ValidationError.
    with pytest.raises(ConnectorRegistryError):
        reg.build("sample", config={"record_count": -1})


def test_registry_describe_emits_schema() -> None:
    reg = ConnectorRegistry()
    reg.register(SampleConnector)
    infos = reg.describe()
    assert len(infos) == 1
    assert infos[0].name == "sample"
    assert infos[0].capabilities == "read"
    assert "record_count" in infos[0].config_schema["properties"]


def test_build_default_registry_only_enables_selected() -> None:
    reg = build_default_connector_registry(enable_fs=True)
    assert reg.names() == ["fs"]
    # Nothing selected → empty registry, still callable.
    empty = build_default_connector_registry()
    assert empty.names() == []


async def test_sample_to_filesystem_round_trip(tmp_path: Path) -> None:
    """End-to-end builtin round-trip through the sync runner."""
    source = SampleConnector(SampleConnector.ConfigModel(record_count=5, batch_size=2))
    dest = FilesystemConnector(
        FilesystemConnector.ConfigModel(
            root_path=str(tmp_path),
            relative_path="out.jsonl",
            format="jsonl",
        )
    )
    runner = SyncRunner(
        source=source,
        destination=dest,
        mapping={"title": "title", "body": "body"},
        direction="pull",
    )
    total_written = 0
    async for batch in runner.execute(idempotency_key="run-1"):
        total_written += batch.written
    assert total_written == 5

    lines = (tmp_path / "out.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    first = json.loads(lines[0])
    assert set(first) == {"title", "body"}  # only mapped keys survive


async def test_sync_runner_skips_records_missing_mapping_path(tmp_path: Path) -> None:
    source = SampleConnector(SampleConnector.ConfigModel(record_count=3, batch_size=3))
    dest = FilesystemConnector(
        FilesystemConnector.ConfigModel(
            root_path=str(tmp_path),
            relative_path="out.jsonl",
        )
    )
    # ``nope`` resolves to a structural miss → every record is skipped.
    runner = SyncRunner(
        source=source,
        destination=dest,
        mapping={"x": "nope"},
        direction="pull",
    )
    written = skipped = 0
    async for batch in runner.execute(idempotency_key="k"):
        written += batch.written
        skipped += batch.skipped
    assert written == 0
    assert skipped == 3


def test_sql_auto_create_table_defaults_off() -> None:
    """The DDL-issuing path is opt-in: the flag defaults to False."""
    cfg = SQLConfig(mode="write", table="t")
    assert cfg.auto_create_table is False
    # Explicit opt-in is honoured when the operator sets it.
    on = SQLConfig(mode="write", table="t", auto_create_table=True)
    assert on.auto_create_table is True

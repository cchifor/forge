"""Sync runner — drives ``Connector.iter_records`` → mapping → ``write_records``.

The runner ties two :class:`~app.connectors.base.Connector` instances
together. The shape is intentionally narrow:

  * One *source* connector providing :meth:`Connector.iter_records`.
  * One *destination* connector providing :meth:`Connector.write_records`.
  * A *mapping* dict whose keys are destination field names and whose
    values are **dotted-path** strings into the source record (e.g.
    ``"body.text"`` reads ``record["body"]["text"]``).
  * A *direction* — ``"pull"`` (source is external, destination internal)
    or ``"push"`` (source internal, destination external). The Literal
    deliberately excludes ``"two_way"`` — bi-directional reconciliation
    needs a conflict-resolution policy first.

Per-page semantics
------------------

The runner pages through :meth:`Connector.iter_records`. For every
``ConnectorPage`` it:

1. Applies the dotted-path mapping to each record. A missing key
   resolves to a structural miss; that record is **skipped** with a
   structured warning, and :attr:`BatchResult.skipped` ticks up.
2. Calls :meth:`Connector.write_records` on the destination with the
   mapped batch and the shared ``idempotency_key``. The same key is
   reused across every batch of one run so a retried run is naturally
   deduped by gateways that honor the convention (HTTP Idempotency-Key,
   SQL ON CONFLICT, etc.).
3. Yields a :class:`BatchResult` carrying the destination's
   ``WriteResult`` plus the source page's *next cursor*. Callers persist
   the cursor so a retry resumes from where the prior attempt stopped.

Errors propagate up unchanged — the runner intentionally does **not**
swallow transient errors; wrap it with your own categorization layer.

Vendored, self-contained: imports only the stdlib + pydantic.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.connectors.base import Connector, WriteResult

log = logging.getLogger(__name__)

SyncDirection = Literal["pull", "push"]
"""Permitted sync directions. ``"two_way"`` is intentionally absent —
bi-directional reconciliation needs a conflict-resolution policy that is
out of scope for the current sync runner."""


class BatchResult(BaseModel):
    """Outcome of a single page through the runner.

    Mirrors :class:`~app.connectors.base.WriteResult` plus a cursor field
    so the caller can persist a resumable checkpoint between batches.
    """

    written: int = 0
    skipped: int = 0
    errors: list[dict[str, Any]] = Field(default_factory=list)
    cursor: dict[str, Any] | None = Field(
        default=None,
        description=(
            "The source page's next cursor. ``None`` when the page was "
            "the last (``ConnectorPage.done is True``). Persist between "
            "batches so retries resume from the last successful page."
        ),
    )
    mapped_records: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "The records forwarded to the destination after applying the "
            "dotted-path mapping. Surfaced so callers can emit step "
            "outputs matching the destination's input shape."
        ),
    )


_MISSING = object()


def _dotted_get(record: dict[str, Any], path: str) -> Any:
    """Resolve a dotted path against a nested dict.

    ``_dotted_get({"body": {"text": "hi"}}, "body.text")`` returns
    ``"hi"``. Missing keys (at any depth) return :data:`_MISSING` so the
    caller can distinguish a real ``None`` value at the path from a
    structural miss. Array indexes and JSONPath expressions are out of
    scope.
    """
    if not path:
        return _MISSING
    cur: Any = record
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


class SyncRunner:
    """Drive a paged source → mapping → destination sync.

    Constructed once per invocation. Statefully holds the pair of
    connectors; :meth:`execute` yields one :class:`BatchResult` per
    source page so the caller can persist checkpoints incrementally.
    """

    def __init__(
        self,
        *,
        source: Connector,
        destination: Connector,
        mapping: dict[str, str],
        direction: SyncDirection,
    ) -> None:
        # Accept ``dict[str, object]`` from a JSON layer but validate to
        # ``dict[str, str]`` here — non-string values are a config error,
        # not a runtime mapping miss.
        bad = {k: v for k, v in mapping.items() if not isinstance(v, str)}
        if bad:
            raise TypeError(
                "SyncRunner.mapping values must be dotted-path strings; "
                f"got non-string values for keys: {sorted(bad)}"
            )
        self._source = source
        self._destination = destination
        self._mapping: dict[str, str] = dict(mapping)
        self._direction: SyncDirection = direction

    @property
    def direction(self) -> SyncDirection:
        return self._direction

    @property
    def source(self) -> Connector:
        return self._source

    @property
    def destination(self) -> Connector:
        return self._destination

    def _apply_mapping(
        self,
        records: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
        """Apply the dotted-path mapping to each record.

        Returns ``(mapped, skipped_count, warnings)``. When the mapping
        is empty the records are forwarded unchanged (the destination is
        expected to know its own write shape).
        """
        if not self._mapping:
            return list(records), 0, []

        mapped: list[dict[str, Any]] = []
        skipped = 0
        warnings: list[dict[str, Any]] = []
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                skipped += 1
                warnings.append({"reason": "non_dict_record", "index": index})
                continue
            out: dict[str, Any] = {}
            missing: list[str] = []
            for dest_key, src_path in self._mapping.items():
                value = _dotted_get(record, src_path)
                if value is _MISSING:
                    missing.append(src_path)
                    continue
                out[dest_key] = value
            if missing:
                skipped += 1
                warning = {
                    "reason": "missing_mapping_path",
                    "index": index,
                    "missing_paths": missing,
                }
                warnings.append(warning)
                log.warning(
                    "sync_runner: skipping record %d due to missing mapping path(s) %s",
                    index,
                    missing,
                    extra={"sync_runner_skip": warning},
                )
                continue
            mapped.append(out)
        return mapped, skipped, warnings

    async def execute(
        self,
        *,
        idempotency_key: str,
    ) -> AsyncIterator[BatchResult]:
        """Run the source → mapping → destination loop.

        Yields one :class:`BatchResult` per source page. The
        ``idempotency_key`` is threaded through to every destination
        write — gateways that honor it dedupe retries naturally.

        On the last page the ``cursor`` field is ``None``; on every prior
        page it carries the source's opaque next-page cursor.
        """
        async for page in self._source.iter_records():
            mapped, skipped_for_mapping, _warnings = self._apply_mapping(page.records)

            if mapped:
                write_result: WriteResult = await self._destination.write_records(
                    mapped,
                    idempotency_key=idempotency_key,
                )
            else:
                # Nothing to write this page — still yield a result so the
                # caller can advance the cursor checkpoint.
                write_result = WriteResult()

            yield BatchResult(
                written=write_result.written,
                skipped=write_result.skipped + skipped_for_mapping,
                errors=list(write_result.errors),
                cursor=None if page.done else page.cursor,
                mapped_records=mapped,
            )
            if page.done:
                return


__all__ = [
    "BatchResult",
    "SyncDirection",
    "SyncRunner",
]

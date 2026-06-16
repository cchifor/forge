"""Invariants for the Redis ``queue_redis`` adapter template.

The adapter (``queue_redis/python/.../adapters/queue/redis.py``) implements the
Python ``QueuePort`` over Redis lists with ``RPOPLPUSH`` for ack-safe delivery.

``enqueue(delay_seconds>0)`` schedules a message into a ``:delayed`` sorted set
keyed by a future delivery timestamp. For that to ever be delivered, the
consume path must promote due entries (score <= now) out of the ``:delayed``
ZSET into the main list. Without that promotion, delayed messages are silently
lost — ``enqueue`` returns a message_id but the message is never consumable.

These tests assert the structural contract over the adapter source: ``consume``
(or a sweeper it drives) reads the ``:delayed`` set via ``ZRANGEBYSCORE`` and
moves due items into the main list.
"""

from __future__ import annotations

from pathlib import Path

_ADAPTER = (
    Path(__file__).resolve().parent.parent
    / "forge"
    / "features"
    / "async_work"
    / "templates"
    / "queue_redis"
    / "python"
    / "files"
    / "src"
    / "app"
    / "adapters"
    / "queue"
    / "redis.py"
)


def _adapter_body() -> str:
    return _ADAPTER.read_text(encoding="utf-8")


def test_adapter_file_present() -> None:
    assert _ADAPTER.is_file(), f"redis adapter missing at {_ADAPTER}"


def test_enqueue_schedules_delayed_zset() -> None:
    """Sanity: the delayed-delivery path zadds into the ``:delayed`` set."""
    body = _adapter_body()
    assert ":delayed" in body
    assert "zadd" in body


def test_consume_promotes_due_delayed_messages() -> None:
    """The consume path must drain the ``:delayed`` ZSET, not just the list.

    Currently ``consume`` only ``rpoplpush``es the main list and never reads
    the ``:delayed`` set, so messages enqueued with ``delay_seconds > 0`` are
    silently lost. A correct implementation polls the ZSET by score (now) and
    promotes due entries into the main list.
    """
    body = _adapter_body()
    # Find the consume coroutine and everything it can reach in the module
    # (a sweeper helper called from consume counts). The simplest structural
    # proof: the adapter must (a) query the delayed set by score and (b) push
    # due items onto the main list.
    assert "zrangebyscore" in body.lower(), (
        "adapter never reads the :delayed set by score — delayed messages "
        "enqueued via delay_seconds>0 are never promoted/delivered"
    )
    # And the delayed key must be referenced from somewhere other than only
    # enqueue: the consume side must look it up too.
    assert body.count(":delayed") >= 2, (
        "the :delayed key is only referenced once (enqueue) — consume never "
        "promotes due delayed messages"
    )

"""WebSocket endpoint for the agent stream.

Contract:
    Connect:  ws://host/api/v1/ws/agent?conversation_id=<uuid>  (conversation_id optional)
    Send:     {"content": "user message"}
    Receive:  a series of AgentEvent JSON frames — conversation_created
              (if starting fresh), user_prompt, text_delta*, agent_status,
              then optionally tool_call / tool_result, closing with
              status=done or status=error.

Auth: not gated by default (same posture as /tools). Wrap the route with
your project's auth dependency before exposing publicly.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.agents.events import (
    ConversationCreated,
    ErrorEvent,
    UserPromptReceived,
)
from app.agents.runner import run_agent

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/agent")
async def agent_stream(
    websocket: WebSocket,
    conversation_id: uuid.UUID | None = Query(default=None),
) -> None:
    await websocket.accept()
    active_conv = conversation_id
    try:
        if active_conv is None:
            active_conv = uuid.uuid4()
            await _send(websocket, ConversationCreated(conversation_id=active_conv))

        while True:
            payload = await websocket.receive_json()
            user_content = str(payload.get("content", "")).strip()
            if not user_content:
                await _send(
                    websocket,
                    ErrorEvent(conversation_id=active_conv, message="empty content"),
                )
                continue

            user_msg_id = uuid.uuid4()
            assistant_msg_id = uuid.uuid4()

            await _send(
                websocket,
                UserPromptReceived(
                    conversation_id=active_conv,
                    message_id=user_msg_id,
                    content=user_content,
                ),
            )

            async for event in run_agent(
                conversation_id=active_conv,
                assistant_message_id=assistant_msg_id,
                user_prompt=user_content,
            ):
                await _send(websocket, event)

    except WebSocketDisconnect:
        logger.info("agent_stream disconnected", extra={"conversation_id": str(active_conv)})
    except Exception as e:  # noqa: BLE001
        logger.exception("agent_stream crashed")
        try:
            await _send(
                websocket,
                ErrorEvent(conversation_id=active_conv, message=f"server error: {e}"),
            )
            await websocket.close(code=1011)
        except Exception:  # noqa: BLE001
            pass


async def _send(ws: WebSocket, event) -> None:
    """Serialize an AgentEvent to JSON and send. Pydantic handles enum /
    datetime / UUID coercion; mode='json' ensures the output is a plain
    dict of JSON-compatible primitives."""
    await ws.send_json(event.model_dump(mode="json"))

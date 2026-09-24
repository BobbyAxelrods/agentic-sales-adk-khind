"""ADK Runner for the Chatwoot webhook, on a durable session store.

Every turn reads and writes the store directly: Vertex AI Agent Engine sessions when
VERTEX_AI_AGENT_ENGINE_ID is set, else process memory (local runs only: lost on restart).
Nothing is cached in the process, so any Cloud Run instance can serve any conversation.
The webhook runs one turn at a time per conversation, so two turns never write one
session at the same time.
"""

from __future__ import annotations

import copy
import logging
import uuid
from typing import Any, Optional

from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import (
    BaseSessionService,
    InMemorySessionService,
    Session,
    VertexAiSessionService,
)
from google.adk.sessions.base_session_service import GetSessionConfig
from google.genai import types as genai_types

from apps.agent import root_agent
from apps.config import settings
from apps.services.replies import build_reply

logger = logging.getLogger(__name__)

APP_NAME = "khind_sales_agent"

TECHNICAL_PROBLEM_LINE = "Maaf, sistem sedang mengalami masalah teknikal. Sila cuba sebentar lagi. 🙏"
NOT_UNDERSTOOD_LINE = "Maaf, saya tidak faham. Boleh ulangi soalan anda? 😊"

_DEFAULT_STATE: dict[str, Any] = {
    "purchase_stage": "discovery",
    "pitched_products": [],
    "initial_media_sent_products": [],
}

# A state read needs the session resource only, not the conversation's events.
_STATE_ONLY = GetSessionConfig(num_recent_events=0)


def _build_session_service() -> BaseSessionService:
    if settings.vertex_ai_agent_engine_id:
        return VertexAiSessionService(
            project=settings.google_cloud_project,
            location=settings.google_cloud_location,
            agent_engine_id=settings.vertex_ai_agent_engine_id,
        )
    logger.warning(
        "VERTEX_AI_AGENT_ENGINE_ID is not set: sessions are kept in process memory "
        "and are lost on restart."
    )
    return InMemorySessionService()


session_service = _build_session_service()

runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=session_service,
)


def session_id_for(conversation_id: str) -> str:
    """Return the session ID of a Chatwoot conversation.

    Agent Engine session IDs allow only [a-z0-9-] and must start with a letter, so the
    older "conv_<id>" form is not valid.
    """
    return f"conv-{conversation_id}"


async def _get_session(session_id: str) -> Optional[Session]:
    return await session_service.get_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
        config=_STATE_ONLY,
    )


async def ensure_session(session_id: str, conversation_id: str) -> dict[str, Any]:
    """Return the session state, and create the session on the customer's first message."""
    session = await _get_session(session_id)
    if session is None:
        state = copy.deepcopy(_DEFAULT_STATE)
        # Read by the escalation tool, which calls Chatwoot itself.
        state["chatwoot_conversation_id"] = conversation_id
        session = await session_service.create_session(
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state=state,
        )
    return copy.deepcopy(session.state)


async def get_session_state(session_id: str) -> dict[str, Any]:
    """Return the stored session state ({} for an unknown session)."""
    session = await _get_session(session_id)
    return copy.deepcopy(session.state) if session else {}


async def patch_session_state(session_id: str, updates: dict[str, Any]) -> None:
    """Write state keys outside an agent turn (webhook side effects such as the media flag).

    The change is stored as an event with a state delta. Editing the state of a session
    that get_session returned would change only a copy.
    """
    session = await _get_session(session_id)
    if session is None:
        logger.warning("patch_session_state: session %s not found", session_id)
        return
    await session_service.append_event(
        session,
        Event(
            invocation_id=f"webhook-{uuid.uuid4().hex}",
            author="user",
            actions=EventActions(state_delta=dict(updates)),
        ),
    )


async def run_turn(
    session_id: str,
    user_message: str,
    state_delta: Optional[dict[str, Any]] = None,
) -> tuple[str, dict[str, Any]]:
    """Run one conversation turn. Returns (reply_text, state after the turn).

    state_delta: state changes stored with the customer's message, before the model runs.
    If the turn fails, the reply is the technical-problem line and the state is {}.
    """
    content = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=user_message)],
    )

    events = []
    try:
        async for event in runner.run_async(
            user_id=session_id,
            session_id=session_id,
            new_message=content,
            state_delta=state_delta or None,
        ):
            events.append(event)
        state = await get_session_state(session_id)
    except Exception:
        logger.exception("ADK runner failed for session %s", session_id)
        return TECHNICAL_PROBLEM_LINE, {}

    # build_reply also keeps text written alongside a tool call (e.g. a handoff line),
    # which is_final_response() alone would drop.
    reply_text = build_reply(events) or NOT_UNDERSTOOD_LINE
    return reply_text, state

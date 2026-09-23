"""ADK Runner singleton — one instance shared across all webhook requests.

Session strategy — write-behind cache:
  - First message from a customer: load session from Vertex AI once, cache in memory.
  - All subsequent turns: served entirely from the in-memory cache — zero Vertex latency.
  - After every turn: state is pushed to Vertex AI in a background task (non-blocking).

This means:
  - Turn latency = LLM + tools only. No Vertex session read/write on the hot path.
  - Conversation history survives server restarts (Vertex is the source of truth).
  - If the background push fails, it is retried on the next turn's background flush.
"""

from __future__ import annotations

import asyncio
import copy
import logging
from typing import Any

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService, VertexAiSessionService
from google.genai import types as genai_types

from apps.agent import root_agent
from apps.config import settings
from apps.services.replies import build_reply

logger = logging.getLogger(__name__)

APP_NAME = "khind_sales_agent"

_DEFAULT_STATE: dict[str, Any] = {
    "purchase_stage": "discovery",
    "pitched_products": [],
    "initial_media_sent_products": [],
    "catalog_sent": False,
}

# ---------------------------------------------------------------------------
# Two-layer session backend
# ---------------------------------------------------------------------------

# Hot layer — serves every turn with zero network latency.
_memory = InMemorySessionService()

# Cold layer — durable store. Only touched on first load and background flush.
_vertex = VertexAiSessionService(
    project=settings.google_cloud_project,
    location=settings.google_cloud_location,
)

# Tracks which session IDs have been loaded from Vertex into memory.
_loaded: set[str] = set()

# ADK Runner uses the in-memory layer exclusively — fast path only.
runner = Runner(
    agent=root_agent,
    app_name=APP_NAME,
    session_service=_memory,
)


# ---------------------------------------------------------------------------
# Session bootstrap
# ---------------------------------------------------------------------------

async def _bootstrap_session(session_id: str) -> None:
    """Load session from Vertex into memory on first contact.

    If Vertex has no session yet (new customer), create one in both layers.
    Subsequent calls for the same session_id are a no-op (guarded by _loaded).
    """
    if session_id in _loaded:
        return

    vertex_session = await asyncio.to_thread(
        _vertex.get_session,
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
    )

    if vertex_session is None:
        # Brand-new customer — create in both layers.
        initial_state = copy.deepcopy(_DEFAULT_STATE)
        await asyncio.to_thread(
            _vertex.create_session,
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state=initial_state,
        )
        _memory.create_session(
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
            state=copy.deepcopy(initial_state),
        )
    else:
        # Returning customer — hydrate memory from Vertex.
        mem_session = _memory.get_session(
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if mem_session is None:
            _memory.create_session(
                app_name=APP_NAME,
                user_id=session_id,
                session_id=session_id,
                state=copy.deepcopy(dict(vertex_session.state)),
            )
        else:
            mem_session.state.update(vertex_session.state)

    _loaded.add(session_id)


# ---------------------------------------------------------------------------
# Background flush to Vertex
# ---------------------------------------------------------------------------

async def _flush_to_vertex(session_id: str) -> None:
    """Push current in-memory state to Vertex AI in the background.

    Called as a fire-and-forget task after every turn — does not block the reply.
    If this fails, Vertex state is stale by one turn but memory is correct,
    so the next turn still works fine and the next flush will catch up.
    """
    mem_session = _memory.get_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
    )
    if mem_session is None:
        return

    state_snapshot = copy.deepcopy(dict(mem_session.state))

    try:
        vertex_session = await asyncio.to_thread(
            _vertex.get_session,
            app_name=APP_NAME,
            user_id=session_id,
            session_id=session_id,
        )
        if vertex_session is not None:
            # Pass state_snapshot as a plain dict argument — no lambda, no shared
            # object mutation across threads.
            await asyncio.to_thread(
                _vertex.update_session,
                app_name=APP_NAME,
                user_id=session_id,
                session_id=session_id,
                state=state_snapshot,
            )
        else:
            # Session disappeared from Vertex (unlikely) — recreate it.
            await asyncio.to_thread(
                _vertex.create_session,
                app_name=APP_NAME,
                user_id=session_id,
                session_id=session_id,
                state=state_snapshot,
            )
    except Exception:
        logger.warning(
            "Background Vertex flush failed for session %s — will retry next turn.",
            session_id,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_session_state(session_id: str) -> dict[str, Any]:
    """Return a snapshot of the current in-memory session state."""
    session = _memory.get_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
    )
    return copy.deepcopy(dict(session.state)) if session else {}


def patch_session_state(session_id: str, updates: dict[str, Any]) -> None:
    """Directly write state keys from the webhook layer (non-LLM side effects).

    Only use for flags like catalog_sent, initial_media_sent_products.
    Do not overwrite state that the agent tools own.
    """
    session = _memory.get_session(
        app_name=APP_NAME,
        user_id=session_id,
        session_id=session_id,
    )
    if session is not None:
        session.state.update(updates)


async def run_turn(session_id: str, user_message: str) -> tuple[str, dict[str, Any]]:
    """Run one conversation turn. Returns (reply_text, updated_state_snapshot).

    Hot path: bootstrap (no-op after first contact) → ADK in-memory turn → snapshot.
    Cold path (background): flush updated state to Vertex AI after replying.
    """
    await _bootstrap_session(session_id)

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
        ):
            events.append(event)
    except Exception:
        logger.exception("ADK runner failed for session %s", session_id)
        fallback = "Maaf, sistem sedang mengalami masalah teknikal. Sila cuba sebentar lagi. 🙏"
        return fallback, get_session_state(session_id)

    # build_reply also keeps text written alongside a tool call (e.g. a handoff line),
    # which is_final_response() alone would drop.
    reply_text = build_reply(events) or "Maaf, saya tidak faham. Boleh ulangi soalan anda? 😊"
    state = get_session_state(session_id)

    # Fire-and-forget — Vertex write does not block the customer reply.
    asyncio.create_task(_flush_to_vertex(session_id))

    return reply_text, state

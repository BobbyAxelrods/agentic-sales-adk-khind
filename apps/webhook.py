"""FastAPI webhook — receives Chatwoot/WhatsApp events, runs ADK agent, delivers replies."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from apps.clients.chatwoot import chatwoot
from apps.clients.gcs import download_bytes
from apps.runner import get_session_state, patch_session_state, run_turn
from apps.services.media_delivery import get_initial_media_plan
from apps.services.product_catalog import get_product_catalog, resolve_product_selection

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])

# Media goes out before the text reply, but the text never waits longer than this.
_MEDIA_WAIT_SECONDS = 20.0
# Strong references so slow media uploads are not garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()


# ---------------------------------------------------------------------------
# Payload extraction helpers
# ---------------------------------------------------------------------------

def _safe_text(value: Any) -> str:
    """Recursively extract a plain string from any nested value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(_safe_text(v) for v in value if _safe_text(v))
    if isinstance(value, dict):
        for key in ("text", "body", "content", "message"):
            if key in value:
                return _safe_text(value[key])
    return str(value).strip()


def _extract_inbound_text(payload: dict[str, Any]) -> str:
    """Return the customer's message text from a Chatwoot webhook payload."""
    if not isinstance(payload, dict):
        return ""
    for key in ("content", "message", "text", "body", "message_text"):
        text = _safe_text(payload.get(key))
        if text:
            return text
    for key in ("messages", "events"):
        items = payload.get(key)
        if isinstance(items, list):
            for item in items:
                text = _extract_inbound_text(item)
                if text:
                    return text
    return ""


def _extract_conversation_id(payload: dict[str, Any]) -> str:
    """Return the Chatwoot conversation ID used for sending outbound replies."""
    if not isinstance(payload, dict):
        return ""
    conv = payload.get("conversation")
    if isinstance(conv, dict):
        cid = conv.get("id")
        if cid:
            return str(cid)
    value = payload.get("conversation_id")
    return str(value) if value else ""


def _extract_session_id(payload: dict[str, Any]) -> str:
    """Return a stable per-customer session key.

    Prefers conversation ID so each Chatwoot conversation is fully isolated.
    Returns empty string if no stable ID can be found — callers must discard
    the event rather than falling back to a shared default session.
    """
    if not isinstance(payload, dict):
        return ""

    conv = payload.get("conversation")
    if isinstance(conv, dict) and conv.get("id"):
        return f"conv_{conv['id']}"

    for key in ("session_id", "conversation_id", "customer_id", "contact_id", "sender_id"):
        value = payload.get(key)
        if value:
            return str(value)

    sender = payload.get("sender") or {}
    if isinstance(sender, dict):
        for key in ("id", "phone_number", "wa_id"):
            value = sender.get(key)
            if value:
                return str(value)

    return ""


def _extract_list_row(payload: dict[str, Any]) -> str | None:
    """Return the product row ID from a WhatsApp interactive list reply, or None."""
    if not isinstance(payload, dict):
        return None

    # Chatwoot standard: content_attributes.item.id
    content_attrs = payload.get("content_attributes") or {}
    if isinstance(content_attrs, dict):
        item = content_attrs.get("item") or {}
        if isinstance(item, dict):
            row_id = item.get("id") or item.get("reply_id") or item.get("value")
            if row_id:
                return str(row_id)

    for key in ("selected_row", "row_id", "product_id"):
        value = payload.get(key)
        if value:
            return str(value)

    # list_reply may be a dict {"id": "prod_xxx"} or a plain string
    list_reply = payload.get("list_reply")
    if isinstance(list_reply, dict):
        row_id = list_reply.get("id") or list_reply.get("reply_id")
        if row_id:
            return str(row_id)
    if isinstance(list_reply, str) and list_reply:
        return list_reply

    return None



# ---------------------------------------------------------------------------
# Post-agent side effects
# ---------------------------------------------------------------------------

async def _deliver_media(
    conversation_id: str,
    product_key: str,
    state: dict[str, Any],
    session_id: str,
) -> None:
    """Send initial product media (2 images + 1 video) on first product selection.

    Downloads each file from GCS and uploads to Chatwoot concurrently.
    Syncs the idempotency flag back into the live session after delivery.
    """
    plan = get_initial_media_plan(product_key, state)

    patch_session_state(
        session_id,
        {"initial_media_sent_products": state.get("initial_media_sent_products", [])},
    )

    if plan["status"] not in ("ok", "incomplete") or not plan["media"]:
        return

    async def _send_one(item: dict[str, Any]) -> None:
        try:
            data, content_type = await asyncio.to_thread(download_bytes, item["gcs_uri"])
            filename = item["gcs_uri"].rsplit("/", 1)[-1]
            await chatwoot.send_attachment(conversation_id, data, filename, content_type)
        except Exception:
            logger.exception("Media delivery failed for %s", item["gcs_uri"])

    await asyncio.gather(*(_send_one(item) for item in plan["media"]))


def _on_media_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Media delivery task failed", exc_info=task.exception())


def _track(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_on_media_task_done)
    return task


async def _set_pending_when_done(media_task: asyncio.Task, conversation_id: str) -> None:
    """Re-apply 'pending' once a late upload finishes, since each API send reopens the chat."""
    await asyncio.wait({media_task})
    await chatwoot.set_conversation_pending(conversation_id)


async def _deliver_media_before_text(
    conversation_id: str,
    product_key: str,
    state: dict[str, Any],
    session_id: str,
    keep_pending: bool,
) -> None:
    """Start media delivery and wait up to _MEDIA_WAIT_SECONDS before the text is sent.

    This gives the sketched order (2 images + 1 video, then USP + location question).
    A slow upload keeps running in the background so the text reply is never held up.
    keep_pending: the caller will set the conversation to pending after its text; a
    late upload then sets it again so the bot gate stays active.
    A turn that handed the chat to an officer gets no media, as it gets no USP.
    """
    if state.get("escalated"):
        return
    media_task = _track(_deliver_media(conversation_id, product_key, state, session_id))
    done, _ = await asyncio.wait({media_task}, timeout=_MEDIA_WAIT_SECONDS)
    if not done and keep_pending:
        _track(_set_pending_when_done(media_task, conversation_id))


async def _maybe_send_catalog(
    conversation_id: str,
    session_id: str,
) -> None:
    """Send the product list menu once per session at the discovery stage.

    Called before run_turn so the LLM knows the menu has already been sent
    and won't describe it again in text.
    """
    state = get_session_state(session_id)
    if state.get("catalog_sent"):
        return
    if state.get("purchase_stage") == "discovery" and not state.get("product_interest"):
        catalog = get_product_catalog()
        await chatwoot.send_product_list(conversation_id, catalog)
        patch_session_state(session_id, {"catalog_sent": True})


async def _maybe_escalate(conversation_id: str, state: dict[str, Any]) -> None:
    """Escalate to human if the agent flagged it but the tool didn't act yet.

    The escalation_tool calls chatwoot.escalate_conversation() directly.
    This function is a safety net for cases where the tool ran without a
    conversation_id in state (e.g. first message before the ID was stored).
    """
    if not state.get("escalated"):
        return
    # If tool already handled it (chatwoot_conversation_id was in state at call time),
    # escalate_conversation was already called — nothing more to do.
    if state.get("chatwoot_conversation_id"):
        return
    # Fallback: conversation_id arrived via webhook but wasn't in state yet.
    label = state.get("escalation_label", "human-required")
    await chatwoot.escalate_conversation(conversation_id, label, state)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "khind-sales-agent"}


@router.post("/webhook")
async def webhook(request: Request) -> dict[str, str]:
    """Receive inbound Chatwoot events and drive the KHIND sales conversation."""
    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object.")

    session_id = _extract_session_id(payload)
    if not session_id:
        # Cannot isolate session — discard rather than risk state corruption.
        logger.warning("Webhook received payload with no identifiable session ID — discarded.")
        return {"status": "ok"}

    conversation_id = _extract_conversation_id(payload)

    # Store conversation_id in session state so ADK tools (e.g. escalation_tool)
    # can call Chatwoot directly without needing to pass it through the LLM.
    if conversation_id:
        patch_session_state(session_id, {"chatwoot_conversation_id": conversation_id})

    # ------------------------------------------------------------------
    # Route A: WhatsApp interactive list reply — deterministic product pick
    # ------------------------------------------------------------------
    list_row = _extract_list_row(payload)
    if list_row:
        product_key = resolve_product_selection(list_row)
        if not product_key:
            # Unknown row ID — discard silently, don't confuse the LLM.
            return {"status": "ok"}

        synthetic_message = f"[PRODUCT_SELECTED:{product_key}]"
        reply_text, state = await run_turn(session_id, synthetic_message)

        if conversation_id:
            # Media first, then text; the pending toggle stays the last API call.
            await _deliver_media_before_text(
                conversation_id, product_key, state, session_id, keep_pending=bool(reply_text)
            )
            if reply_text:
                await chatwoot.send_text(conversation_id, reply_text)
                await chatwoot.set_conversation_pending(conversation_id)

        return {"status": "ok"}

    # ------------------------------------------------------------------
    # Route B: Regular text message — full LLM turn
    # ------------------------------------------------------------------
    message_text = _extract_inbound_text(payload)
    if not message_text:
        return {"status": "ok"}

    if conversation_id:
        # Send catalog BEFORE the agent turn so the LLM knows it was already sent.
        await _maybe_send_catalog(conversation_id, session_id)

    reply_text, state = await run_turn(session_id, message_text)

    if conversation_id:
        # Media first (a no-op after the first pick of a product), then text.
        product_key = state.get("product_interest", "")
        if product_key:
            await _deliver_media_before_text(
                conversation_id,
                product_key,
                state,
                session_id,
                keep_pending=bool(reply_text),
            )

        if reply_text:
            await chatwoot.send_text(conversation_id, reply_text)
            # Keep bot gate active — Chatwoot toggles to 'open' on every outbound API send,
            # so this must stay the last send of the turn.
            if not state.get("escalated"):
                await chatwoot.set_conversation_pending(conversation_id)

        await _maybe_escalate(conversation_id, state)

    return {"status": "ok"}

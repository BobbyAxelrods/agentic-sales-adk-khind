"""FastAPI webhook — receives Chatwoot agent-bot events, runs the ADK agent, delivers replies.

Chatwoot waits about 5 s for the webhook response. A slower response or an error opens the
pending chat for officers ("marked open by system due to an error with the agent bot").
So the route checks the signature, keeps only customer messages in chats the bot owns, and
returns 200 at once. The turn runs in the background, one at a time per conversation, in
the order the messages arrived.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException, Request

from apps.clients.chatwoot import chatwoot
from apps.clients.gcs import download_bytes
from apps.config import settings
from apps.prompts.khind_prompts import IC_PHOTOS_RECEIVED_LINE
from apps.runner import ensure_session, patch_session_state, run_turn, session_id_for
from apps.services.media_delivery import get_initial_media_plan

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])

# Media goes out before the text reply, but the text never waits longer than this.
_MEDIA_WAIT_SECONDS = 20.0
# Chatwoot signs "<timestamp>.<body>". A timestamp further off than this is refused, so an
# old signed request cannot be sent again later.
_SIGNATURE_MAX_AGE_SECONDS = 300
# Message IDs already accepted, so a repeated delivery runs no second turn.
_SEEN_MESSAGE_LIMIT = 1000
# Photos after a complete application go to an officer with this label.
IC_PHOTOS_LABEL = "human-required"

# Strong references so background work is not garbage-collected mid-flight.
_background_tasks: set[asyncio.Task] = set()
_seen_message_ids: OrderedDict[Any, None] = OrderedDict()
# One lock per conversation that has a turn running or waiting; removed when idle.
_conversation_locks: dict[str, asyncio.Lock] = {}
_conversation_waiting: dict[str, int] = {}


@dataclass(frozen=True)
class CustomerMessage:
    id: Any
    conversation_id: str
    text: str
    has_image: bool


# ---------------------------------------------------------------------------
# Request checks
# ---------------------------------------------------------------------------

def _signature_ok(body: bytes, timestamp: str | None, signature: str | None) -> bool:
    """Check X-Chatwoot-Signature: "sha256=" + HMAC-SHA256(secret, "<timestamp>.<body>").

    The secret is the agent bot's Webhook Secret. With no secret set, every call fails.
    """
    secret = settings.chatwoot_webhook_secret
    if not secret or not timestamp or not signature:
        return False
    try:
        age = abs(time.time() - int(timestamp))
    except ValueError:
        return False
    if age > _SIGNATURE_MAX_AGE_SECONDS:
        return False
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={digest}", signature)


def _customer_message(payload: Any) -> CustomerMessage | None:
    """Return the customer's message, or None for every event the bot must not answer.

    The agent bot receives every message event of its inbox: its own replies and the
    officers' (outgoing), private notes, WhatsApp delivered/read updates (message_updated),
    and messages after a handoff. Only a new, public, incoming message in a chat that is
    still pending (owned by the bot) gets a reply.
    """
    if not isinstance(payload, dict) or payload.get("event") != "message_created":
        return None
    if payload.get("message_type") != "incoming" or payload.get("private"):
        return None
    conversation = payload.get("conversation")
    if not isinstance(conversation, dict) or conversation.get("status") != "pending":
        return None
    conversation_id = conversation.get("id")
    if not conversation_id:
        return None
    content = payload.get("content")
    text = content.strip() if isinstance(content, str) else ""
    attachments = payload.get("attachments") or []
    has_image = any(isinstance(a, dict) and a.get("file_type") == "image" for a in attachments)
    if not text and not has_image:
        return None
    return CustomerMessage(payload.get("id"), str(conversation_id), text, has_image)


def _seen_before(message_id: Any) -> bool:
    """Record the message ID; True if it was already accepted."""
    if message_id is None:
        return False
    if message_id in _seen_message_ids:
        return True
    _seen_message_ids[message_id] = None
    if len(_seen_message_ids) > _SEEN_MESSAGE_LIMIT:
        _seen_message_ids.popitem(last=False)
    return False


# ---------------------------------------------------------------------------
# Background work
# ---------------------------------------------------------------------------

def _on_task_done(task: asyncio.Task) -> None:
    _background_tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        logger.error("Webhook background task failed", exc_info=task.exception())


def _track(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_on_task_done)
    return task


async def _in_order(conversation_id: str, handle: Callable[[], Awaitable[None]]) -> None:
    """Run handle() after the earlier messages of this conversation (asyncio.Lock is FIFO)."""
    lock = _conversation_locks.setdefault(conversation_id, asyncio.Lock())
    _conversation_waiting[conversation_id] = _conversation_waiting.get(conversation_id, 0) + 1
    try:
        async with lock:
            await handle()
    finally:
        _conversation_waiting[conversation_id] -= 1
        if not _conversation_waiting[conversation_id]:
            del _conversation_waiting[conversation_id]
            del _conversation_locks[conversation_id]


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

    Downloads each file from GCS and uploads to Chatwoot concurrently. The product is
    marked as sent in the session before the uploads start, so it is sent at most once.
    """
    plan = await asyncio.to_thread(get_initial_media_plan, product_key, state)
    if plan["status"] not in ("ok", "incomplete") or not plan["media"]:
        return

    await patch_session_state(
        session_id,
        {"initial_media_sent_products": state["initial_media_sent_products"]},
    )

    async def _send_one(item: dict[str, Any]) -> None:
        try:
            data, content_type = await asyncio.to_thread(download_bytes, item["gcs_uri"])
            filename = item["gcs_uri"].rsplit("/", 1)[-1]
            await chatwoot.send_attachment(conversation_id, data, filename, content_type)
        except Exception:
            logger.exception("Media delivery failed for %s", item["gcs_uri"])

    await asyncio.gather(*(_send_one(item) for item in plan["media"]))


async def _deliver_media_before_text(
    conversation_id: str,
    product_key: str,
    state: dict[str, Any],
    session_id: str,
) -> None:
    """Start media delivery and wait up to _MEDIA_WAIT_SECONDS before the text is sent.

    This gives the sketched order (2 images + 1 video, then USP + location question).
    A slow upload keeps running in the background so the text reply is never held up.
    """
    media_task = _track(_deliver_media(conversation_id, product_key, state, session_id))
    await asyncio.wait({media_task}, timeout=_MEDIA_WAIT_SECONDS)


async def _hand_over_ic_photos(conversation_id: str, session_id: str, state: dict[str, Any]) -> None:
    """Photos after a complete application: hand the chat to an officer, with no model turn.

    The last form message asks for the IC photos, and the model cannot see images.
    """
    await chatwoot.escalate_conversation(conversation_id, IC_PHOTOS_LABEL, state)
    await chatwoot.send_text(conversation_id, IC_PHOTOS_RECEIVED_LINE)
    await patch_session_state(session_id, {"escalated": True, "escalation_label": IC_PHOTOS_LABEL})


async def _handle_message(message: CustomerMessage) -> None:
    """Answer one customer message: agent turn, media, then the text reply."""
    conversation_id = message.conversation_id
    session_id = session_id_for(conversation_id)
    state = await ensure_session(session_id, conversation_id)
    # Stored with the customer's message, before the model runs.
    turn_delta: dict[str, Any] = {}

    if state.get("escalated"):
        # The chat is pending again after a handoff: an officer gave it back, or it was
        # resolved and the customer wrote again. The bot resumes the flow. A message that
        # waited behind the handoff turn still says "pending", so ask Chatwoot for the
        # status now; if that fails, the payload's status stands.
        if await chatwoot.get_conversation_status(conversation_id) not in (None, "pending"):
            return
        turn_delta.update(escalated=False, escalation_label=None)

    if message.has_image and state.get("application_complete"):
        await _hand_over_ic_photos(conversation_id, session_id, state)
        return
    if not message.text:
        return

    # The model's greeting carries the product list (PRODUCT_MENU), so the webhook sends none.
    reply_text, state = await run_turn(session_id, message.text, turn_delta)

    # Media first (a no-op after the first pick of a product), then text. A turn that
    # handed the chat to an officer gets no media, as it gets no USP.
    product_key = state.get("product_interest")
    if product_key and not state.get("escalated"):
        await _deliver_media_before_text(conversation_id, product_key, state, session_id)
    if reply_text:
        await chatwoot.send_text(conversation_id, reply_text)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "khind-sales-agent"}


@router.post("/webhook")
async def webhook(request: Request) -> dict[str, str]:
    """Check and filter a Chatwoot event, then run the turn in the background."""
    body = await request.body()
    if not _signature_ok(
        body,
        request.headers.get("X-Chatwoot-Timestamp"),
        request.headers.get("X-Chatwoot-Signature"),
    ):
        logger.warning("Webhook call without a valid Chatwoot signature: rejected.")
        raise HTTPException(status_code=401, detail="Invalid signature.")
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Body must be JSON.") from None

    message = _customer_message(payload)
    if message is None:
        return {"status": "ignored"}
    if _seen_before(message.id):
        return {"status": "duplicate"}
    _track(_in_order(message.conversation_id, lambda: _handle_message(message)))
    return {"status": "accepted"}

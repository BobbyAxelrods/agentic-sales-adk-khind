"""Shape the text the customer receives from one agent turn.

- insert_pending_usp: after_model_callback that puts the approved product USP, word
  for word, at the top of the model's reply after a first product pick. The USP
  becomes part of the model's own message, so adk web, the API server and the
  webhook all show exactly what the customer gets.
- build_reply: turns one turn's ADK events into the reply text for the customer.

Both are pure functions over ADK objects, so they can be tested without Vertex AI
or Chatwoot.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from google.adk.agents.callback_context import CallbackContext
from google.adk.events import Event
from google.adk.models import LlmResponse
from google.genai import types as genai_types

from apps.prompts.khind_prompts import (
    DEFAULT_HANDOFF_LINE,
    HANDOFF_FALLBACK_LINES,
    KHIND_PRODUCT_USPS,
)

PENDING_USP_KEY = "pending_usp_products"
_ESCALATION_TOOL = "escalate_to_live_agent"


def _visible_text(parts: Optional[list[genai_types.Part]]) -> str:
    """Join the customer-visible text of the given parts (thought parts excluded)."""
    return "".join(p.text for p in parts or [] if p.text and not p.thought).strip()


# A bold title line such as "*KHIND ChillMaster 592L* ✨" (up to 3 trailing symbols).
_TITLE_LINE = re.compile(r"^\*[^*\n]+\*\s*\S{0,3}$")


def _strip_feature_blocks(text: str) -> str:
    """Remove model-written product feature blocks: an optional bold title line
    followed by ✅ lines and optional "*(...)*" note lines.

    Only used on a reply that is getting an approved USP from code. The model
    sometimes writes its own version (at times with unapproved claims), so every
    such block is dropped and the approved text is the only one sent.
    """
    lines = text.split("\n")
    kept: list[str] = []
    i = 0
    while i < len(lines):
        j = i + 1 if _TITLE_LINE.match(lines[i].strip()) else i
        if j < len(lines) and lines[j].strip().startswith("✅"):
            while j < len(lines) and lines[j].strip().startswith(("✅", "*(")):
                j += 1
            i = j
            continue
        kept.append(lines[i])
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()


def insert_pending_usp(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Put each pending product USP, word for word, above the model's text reply.

    set_product_interest queues a product key on its first pick. Responses that
    call a tool are left alone: the USP goes on the text reply that follows. Any
    feature block the model wrote itself is removed, so the approved USP is the
    only product description in the message.
    """
    pending = list(callback_context.state.get(PENDING_USP_KEY) or [])
    if not pending or llm_response.partial or llm_response.error_code:
        return None
    parts = list(llm_response.content.parts or []) if llm_response.content else []
    if any(p.function_call for p in parts):
        return None

    usps = [KHIND_PRODUCT_USPS[key] for key in pending if key in KHIND_PRODUCT_USPS]
    callback_context.state[PENDING_USP_KEY] = []
    if not usps:
        return None

    prefix = "\n\n".join(usps)
    text_part = next((p for p in parts if p.text and not p.thought), None)
    if text_part is not None:
        rest = _strip_feature_blocks(text_part.text)
        text_part.text = f"{prefix}\n\n{rest}" if rest else prefix
    else:
        parts.append(genai_types.Part(text=prefix))

    if llm_response.content is None:
        llm_response.content = genai_types.Content(role="model", parts=parts)
    else:
        llm_response.content.parts = parts
    return llm_response


def build_reply(events: Iterable[Event]) -> str:
    """Return the customer reply for one turn's events ("" if there is nothing to send).

    - Text is taken from every non-partial agent event, including text the model
      writes in the same step as a tool call. is_final_response() alone drops that.
    - Exact repeats are skipped. Chunks are joined with a blank line.
    - If the handoff line came with the escalate_to_live_agent call, any later text
      in the turn is ignored, so the customer gets one handoff line, not two.
    - A handoff turn with no text at all gets the fixed fallback line for its label.
    """
    chunks: list[str] = []
    handoff_label: Optional[str] = None
    handoff_line_sent = False

    for event in events:
        if event.partial or event.author == "user" or not event.content:
            continue
        text = _visible_text(event.content.parts)
        escalations = [
            call for call in event.get_function_calls() if call.name == _ESCALATION_TOOL
        ]
        if text and not handoff_line_sent and text not in chunks:
            chunks.append(text)
        if escalations:
            handoff_label = str((escalations[-1].args or {}).get("label", "")).strip().lower()
            if text:
                handoff_line_sent = True

    reply = "\n\n".join(chunks)
    if not reply and handoff_label is not None:
        reply = HANDOFF_FALLBACK_LINES.get(handoff_label, DEFAULT_HANDOFF_LINE)
    return reply

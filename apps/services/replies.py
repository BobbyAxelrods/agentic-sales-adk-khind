"""Shape the text the customer receives from one agent turn.

- drop_text_beside_coverage_call: after_model_callback that removes text written in the
  same response as an advance_purchase_stage call, before the coverage verdict exists.
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
    LOCATION_QUESTION,
)

PENDING_USP_KEY = "pending_usp_products"
# Set to the turn's invocation id by the tools whose results the reply must carry
# (query_product_info, advance_purchase_stage).
REPLY_FACTS_KEY = "reply_facts_invocation"
_ESCALATION_TOOL = "escalate_to_live_agent"
_COVERAGE_TOOL = "advance_purchase_stage"


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


def _closing_question(text: str) -> str:
    """The last paragraph that asks something, else the last paragraph."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    asking = [p for p in paragraphs if "?" in p]
    return (asking or paragraphs or [""])[-1]


def drop_text_beside_coverage_call(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Remove text the model writes in the same response as an advance_purchase_stage call.

    The coverage verdict comes from that tool. A line such as "kawasan ... ada dalam
    liputan" written before the result could contradict it, and build_reply keeps text
    written beside tool calls. The reply is written after the tool returns.
    """
    if llm_response.partial or not llm_response.content:
        return None
    parts = list(llm_response.content.parts or [])
    if not any(p.function_call and p.function_call.name == _COVERAGE_TOOL for p in parts):
        return None
    kept = [p for p in parts if not (p.text and not p.thought)]
    if len(kept) == len(parts):
        return None
    llm_response.content.parts = kept
    return llm_response


def insert_pending_usp(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Put each pending product USP, word for word, above the model's text reply.

    set_product_interest queues a product key on its first pick. Responses that
    call a tool are left alone: the USP goes on the text reply that follows. Any
    feature block the model wrote itself is removed, so the approved USP is the
    only product description in the message. On a plain pick (no product answer or
    coverage verdict in the turn) only the model's closing question is kept: the model
    tends to add its own praise or claims there. A turn that handed the chat to an officer
    gets no USP: the customer gets the handoff line only.
    """
    pending = list(callback_context.state.get(PENDING_USP_KEY) or [])
    if not pending or llm_response.partial or llm_response.error_code:
        return None
    parts = list(llm_response.content.parts or []) if llm_response.content else []
    if any(p.function_call for p in parts):
        return None
    if callback_context.state.get("escalated"):
        # Otherwise an empty handoff reply would become USP-only, and build_reply would
        # never add the fixed handoff line.
        callback_context.state[PENDING_USP_KEY] = []
        return None

    usps = [KHIND_PRODUCT_USPS[key] for key in pending if key in KHIND_PRODUCT_USPS]
    callback_context.state[PENDING_USP_KEY] = []
    if not usps:
        return None

    prefix = "\n\n".join(usps)
    text_part = next((p for p in parts if p.text and not p.thought), None)
    if text_part is not None:
        rest = _strip_feature_blocks(text_part.text)
        if callback_context.state.get(REPLY_FACTS_KEY) != callback_context.invocation_id:
            # A plain pick: at the location step the only reply is the fixed location
            # question; at a later step, the model's closing question.
            if callback_context.state.get("purchase_stage") == "location":
                rest = LOCATION_QUESTION
            else:
                rest = _closing_question(rest)
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

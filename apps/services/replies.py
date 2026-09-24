"""Shape the text the customer receives from one agent turn.

- strip_personal_values: after_model_callback that removes the personal values the customer
  gave (name, IC, phone, email, address) from the model's text.
- drop_text_beside_coverage_or_handoff_call: after_model_callback that removes text written
  in the same response as an advance_purchase_stage or escalate_to_live_agent call.
- insert_pending_usp: after_model_callback that puts the approved product USP, word
  for word, at the top of the model's reply after a first product pick. The USP
  becomes part of the model's own message, so adk web, the API server and the
  webhook all show exactly what the customer gets.
- fill_empty_handoff_reply: after_model_callback that gives a handoff turn's empty final
  reply the label's fixed line.
- build_reply: turns one turn's ADK events into the reply text for the customer.

All are pure functions over ADK objects, so they can be tested without Vertex AI
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
# Set to the turn's invocation id when the chat is handed to an officer (see
# apps.tools.escalation_tool.hand_off).
HANDOFF_TURN_KEY = "escalation_invocation"
_ESCALATION_TOOL = "escalate_to_live_agent"
_COVERAGE_TOOL = "advance_purchase_stage"
_SAVE_TOOL = "save_application_details"
# Text the model writes beside these calls is never sent (see
# drop_text_beside_coverage_or_handoff_call).
_TEXT_FREE_TOOLS = frozenset({_COVERAGE_TOOL, _ESCALATION_TOOL})

# Application fields that must never be repeated to the customer (PDPA).
_NAME_FIELDS = ("full_name", "emergency_contact_name")
_NUMBER_FIELDS = ("ic_number", "whatsapp_number", "emergency_contact_phone")
_TEXT_FIELDS = ("email", "installation_address")
# Words that join the parts of a Malaysian name; they are not removed on their own.
_NAME_LINKS = frozenset({"bin", "binti", "bt", "bte", "a/l", "a/p", "anak", "s/o", "d/o"})
# An optional title before a name, but not the "tuan" of "cik/tuan".
_TITLE = r"(?:(?<![\w/])(?:Encik|En\.|Cik|Tuan|Puan|Pn\.)\s+)?"


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


def _personal_patterns(details: dict) -> list[re.Pattern]:
    """Patterns for the personal values in `details`: full names first, single name words last."""
    names: list[re.Pattern] = []
    others: list[re.Pattern] = []
    words: list[re.Pattern] = []
    for field in _NAME_FIELDS:
        value = str(details.get(field) or "").strip()
        if not value:
            continue
        # A removed name takes its leading comma and title with it ("Terima kasih, Ali!").
        names.append(re.compile(rf"(?:,\s*)?{_TITLE}(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE))
        for word in value.split():
            if len(word) >= 3 and word.lower() not in _NAME_LINKS:
                # Only where it is capitalised, so "Kasih" in a name leaves "terima kasih" alone.
                cap = word[0].upper() + word[1:].lower()
                words.append(re.compile(rf"(?:,\s*)?{_TITLE}(?<!\w){re.escape(cap)}(?!\w)"))
    for field in _NUMBER_FIELDS:
        digits = re.sub(r"\D", "", str(details.get(field) or ""))
        if len(digits) >= 7:
            # The same digits, with or without dashes and spaces between them.
            others.append(re.compile(r"(?<!\d)" + r"[-\s]?".join(digits) + r"(?!\d)"))
    for field in _TEXT_FIELDS:
        value = str(details.get(field) or "").strip()
        if value:
            others.append(re.compile(re.escape(value), re.IGNORECASE))
    return names + others + words


def _remove_all(text: str, patterns: list[re.Pattern]) -> str:
    """Remove every match, then tidy the spaces and punctuation left behind."""
    cleaned = text
    for pattern in patterns:
        cleaned = pattern.sub("", cleaned)
    if cleaned == text:
        return text
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+([,.!?])", r"\1", cleaned)
    cleaned = re.sub(r",([.!?])", r"\1", cleaned)
    cleaned = re.sub(r"(^|\n)[ \t]*,[ \t]*", r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+(?=\n|$)", "", cleaned)
    return re.sub(r"(^|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), cleaned)


def strip_personal_values(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
    """Remove the personal values the customer gave from the model's text (PDPA).

    In the form step the model thanked customers by name ("Terima kasih, Ali bin Abu!") in
    most scripted runs, whatever the prompt said. The values come from the saved application
    details and from any save_application_details call in the same response, so text written
    beside that call is covered too. A name word is removed only where it is capitalised; a
    number with or without separators.

    Edits the response in place and returns None, so the callbacks after it still run (ADK
    stops at the first callback that returns a response).
    """
    if llm_response.partial or not llm_response.content:
        return None
    parts = llm_response.content.parts or []
    details = dict(callback_context.state.get("application_details") or {})
    for part in parts:
        if part.function_call and part.function_call.name == _SAVE_TOOL:
            details.update({k: v for k, v in (part.function_call.args or {}).items() if v})
    patterns = _personal_patterns(details)
    if not patterns:
        return None
    for part in parts:
        if part.text and not part.thought:
            part.text = _remove_all(part.text, patterns)
    return None


def drop_text_beside_coverage_or_handoff_call(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Remove text the model writes in the same response as a coverage or handoff call.

    - advance_purchase_stage: the coverage verdict comes from the tool. A line such as
      "kawasan ... ada dalam liputan" written before the result could contradict it.
    - escalate_to_live_agent: in the 2026-09-24 rerun (B6) the model wrote its English
      reasoning here, and it went out as the handoff line.
    build_reply keeps text written beside other tool calls. The reply is written after the
    tool returns; a handoff turn that ends with no text gets its label's fixed line.
    """
    if llm_response.partial or not llm_response.content:
        return None
    parts = list(llm_response.content.parts or [])
    if not any(p.function_call and p.function_call.name in _TEXT_FREE_TOOLS for p in parts):
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


def fill_empty_handoff_reply(
    callback_context: CallbackContext, llm_response: LlmResponse
) -> Optional[LlmResponse]:
    """Give the final reply of a handoff turn the label's fixed line if the model wrote none.

    Text written beside the escalate call is dropped, so without this the customer could
    get no handoff line. build_reply has the same fallback; this one also covers adk web.
    """
    state = callback_context.state
    if llm_response.partial or llm_response.error_code:
        return None
    if state.get(HANDOFF_TURN_KEY) != callback_context.invocation_id:
        return None
    parts = list(llm_response.content.parts or []) if llm_response.content else []
    if any(p.function_call for p in parts) or _visible_text(parts):
        return None
    label = str(state.get("escalation_label") or "")
    parts.append(genai_types.Part(text=HANDOFF_FALLBACK_LINES.get(label, DEFAULT_HANDOFF_LINE)))
    llm_response.content = genai_types.Content(role="model", parts=parts)
    return llm_response


def build_reply(events: Iterable[Event]) -> str:
    """Return the customer reply for one turn's events ("" if there is nothing to send).

    - Text is taken from every non-partial agent event, including text the model
      writes in the same step as a tool call. is_final_response() alone drops that.
      Text beside a coverage or handoff call is the exception: it is never sent (the
      after-model callback removes it too).
    - Exact repeats are skipped. Chunks are joined with a blank line.
    - A handoff turn with no text at all gets the fixed fallback line for its label. The
      handoff is read from the tool results, so a handoff made by advance_purchase_stage
      counts too.
    """
    chunks: list[str] = []
    handoff_label: Optional[str] = None

    for event in events:
        if event.partial or event.author == "user" or not event.content:
            continue
        for response in event.get_function_responses():
            result = response.response or {}
            if result.get("escalated"):
                handoff_label = str(result.get("label", "")).strip().lower()
        if any(call.name in _TEXT_FREE_TOOLS for call in event.get_function_calls()):
            continue
        text = _visible_text(event.content.parts)
        if text and text not in chunks:
            chunks.append(text)

    reply = "\n\n".join(chunks)
    if not reply and handoff_label is not None:
        reply = HANDOFF_FALLBACK_LINES.get(handoff_label, DEFAULT_HANDOFF_LINE)
    return reply

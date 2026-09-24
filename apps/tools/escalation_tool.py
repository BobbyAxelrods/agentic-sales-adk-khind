"""ADK escalation tool — calls Chatwoot directly to hand off to a human agent."""

from google.adk.tools import ToolContext

from apps.clients.chatwoot import chatwoot
from apps.services.replies import HANDOFF_TURN_KEY


# Applied by advance_purchase_stage itself when the area is not covered.
COVERAGE_HANDOFF_LABEL = "coverage-unsupported-alternative"

ESCALATION_LABELS = frozenset(
    {
        "coverage-unsupported-alternative",
        "not-working",
        "human-required",
        "angry-customer",
        "rag-error",
    }
)


async def escalate_to_live_agent(label: str, tool_context: ToolContext) -> dict:
    """Escalate this conversation to a live human agent in Chatwoot.

    Actions performed:
    1. Sets Chatwoot conversation status to 'open' (disables bot gate).
    2. In parallel: applies label, posts private context note, assigns to agent/team.

    Args:
        label: Chatwoot label to apply — must be one of the approved values:
               'human-required', 'angry-customer', 'not-working', 'rag-error'.
               ('coverage-unsupported-alternative' is applied by advance_purchase_stage
               itself.)
        tool_context: ADK tool context (injected by framework).

    Returns:
        dict with 'escalated': bool.
    """
    normalized_label = label.strip().lower()
    if normalized_label not in ESCALATION_LABELS:
        return {
            "status": "error",
            "escalated": False,
            "message": f"Invalid label. Use one of: {sorted(ESCALATION_LABELS)}",
        }
    return await hand_off(normalized_label, tool_context)


async def hand_off(label: str, tool_context: ToolContext) -> dict:
    """Hand the conversation to a live agent with an approved label.

    Used by escalate_to_live_agent and, for an area that is not covered, by
    advance_purchase_stage. A second handoff with the same label in the same turn is a
    no-op, so the model repeating the call posts no second Chatwoot note.
    """
    state = tool_context.state
    if state.get(HANDOFF_TURN_KEY) == tool_context.invocation_id and state.get("escalation_label") == label:
        return {"status": "ok", "escalated": True, "label": label, "already_escalated": True}

    conversation_id: str = state.get("chatwoot_conversation_id", "")
    ok = True
    if conversation_id:
        # ADK's State is not a Mapping: dict(state) raises KeyError(0), so use to_dict().
        ok = await chatwoot.escalate_conversation(conversation_id, label, state.to_dict())

    state["escalated"] = True
    state["escalation_label"] = label
    # Read by apps.services.replies.fill_empty_handoff_reply.
    state[HANDOFF_TURN_KEY] = tool_context.invocation_id

    if not conversation_id:
        # No conversation ID (e.g. adk web): state only; the webhook skips the Chatwoot call.
        return {"status": "ok", "escalated": True, "label": label, "chatwoot": "skipped"}
    if not ok:
        return {"status": "error", "escalated": True, "label": label, "chatwoot": "failed"}
    return {"status": "ok", "escalated": True, "label": label}

"""ADK escalation tool — calls Chatwoot directly to hand off to a human agent."""

from google.adk.tools import ToolContext

from apps.clients.chatwoot import chatwoot


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
               'human-required', 'angry-customer', 'not-working',
               'coverage-unsupported-alternative', 'rag-error'.
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

    conversation_id: str = tool_context.state.get("chatwoot_conversation_id", "")
    if not conversation_id:
        # No conversation ID — mark state only; webhook will skip Chatwoot call.
        tool_context.state["escalated"] = True
        tool_context.state["escalation_label"] = normalized_label
        return {"status": "ok", "escalated": True, "label": normalized_label, "chatwoot": "skipped"}

    # ADK's State is not a Mapping: dict(state) raises KeyError(0), so use to_dict().
    ok = await chatwoot.escalate_conversation(
        conversation_id, normalized_label, tool_context.state.to_dict()
    )

    tool_context.state["escalated"] = True
    tool_context.state["escalation_label"] = normalized_label

    if not ok:
        return {"status": "error", "escalated": True, "label": normalized_label, "chatwoot": "failed"}

    return {"status": "ok", "escalated": True, "label": normalized_label}

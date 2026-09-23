"""State-driven prompt assembler for the KHIND WhatsApp sales agent."""

from apps.prompts.khind_prompts import (
    CLOSING_FRAGMENT_RAW,
    COVERAGE_FRAGMENT_RAW,
    DISCOVERY_FRAGMENT_RAW,
    DISCOVERY_QUESTION,
    IC_PHOTO_QUESTION,
    KERJA_QUESTION,
    KHIND_CORE_RAW,
    KHIND_ESCALATION_RAW,
    LOCATION_QUESTION,
)


def pending_step(state) -> str:
    """The step the customer has not finished, with the question that asks for it.

    Every reply except a handoff ends with this question, so answering a side question
    or showing the product list never loses the step.
    """
    if state.get("escalated"):
        return ("None. The chat was handed to an officer: reply briefly and politely, "
                "do not sell and do not ask a sales question.")
    if not state.get("product_interest"):
        return ("Choose a product. If the message names or asks about ONE product (e.g. \"Ada aircond "
                "tak?\"), call set_product_interest now instead of asking. Otherwise ask: "
                f'"{DISCOVERY_QUESTION}"')
    if state.get("purchase_stage", "discovery") not in ("qualification", "form"):
        return f'Postcode & area. Question: "{LOCATION_QUESTION}"'
    if state.get("application_complete"):
        return f'IC photos. Question: "{IC_PHOTO_QUESTION}"'
    if state.get("application_form_sent"):
        return ("Application form. Ask only for the fields still missing (missing_fields); "
                "never resend the form.")
    return (f'Employment / RM1. If the customer has not said whether they work, ask: "{KERJA_QUESTION}" '
            "If they said they work, invite them to the eligibility check (the RM1 line).")


def get_khind_instruction(context=None) -> str:
    """Assemble only the prompt fragment needed for the current sales stage."""
    state = getattr(context, "state", {}) if context else {}
    product_interest = state.get("product_interest", "")
    pitched_products = set(state.get("pitched_products", []))
    purchase_stage = state.get("purchase_stage", "discovery")
    language = state.get("language", "bm")

    parts = [
        KHIND_CORE_RAW,
        KHIND_ESCALATION_RAW,
        (
            "\n## Current State\n"
            f"- Active Product: {product_interest or 'None'}\n"
            f"- Pitched Products: {sorted(pitched_products)}\n"
            f"- Stage: {purchase_stage}\n"
            f"- Pending step: {pending_step(state)}\n"
            f"- Language: {language}\n"
        ),
    ]

    if not product_interest:
        parts.append(DISCOVERY_FRAGMENT_RAW)
    elif purchase_stage in ("qualification", "form"):
        parts.append(CLOSING_FRAGMENT_RAW)
    else:
        # "location", or a legacy "discovery"/"product" session that already has a product.
        parts.append(COVERAGE_FRAGMENT_RAW)

    return "\n\n".join(parts)

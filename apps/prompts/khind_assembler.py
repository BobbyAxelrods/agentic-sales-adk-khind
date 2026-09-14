"""State-driven prompt assembler for the KHIND WhatsApp sales agent."""

from apps.prompts.khind_prompts import (
    CLOSING_FRAGMENT_RAW,
    COVERAGE_FRAGMENT_RAW,
    DISCOVERY_FRAGMENT_RAW,
    KHIND_CORE_RAW,
    KHIND_ESCALATION_RAW,
    PRODUCT_RAG_FRAGMENT_RAW,
    PRODUCT_USP_FRAGMENT_RAW,
)


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
            f"- Language: {language}\n"
        ),
    ]

    if purchase_stage == "discovery" and not product_interest:
        parts.append(DISCOVERY_FRAGMENT_RAW)
    elif purchase_stage in ("discovery", "product") and product_interest:
        parts.append(
            PRODUCT_RAG_FRAGMENT_RAW
            if product_interest in pitched_products
            else PRODUCT_USP_FRAGMENT_RAW
        )
    elif purchase_stage == "location":
        parts.append(COVERAGE_FRAGMENT_RAW)
    elif purchase_stage in ("qualification", "form"):
        parts.append(CLOSING_FRAGMENT_RAW)

    return "\n\n".join(parts)
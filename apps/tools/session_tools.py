"""ADK tools that maintain the KHIND sales journey session state."""

from google.adk.tools import ToolContext

from apps.prompts.khind_prompts import KHIND_PRODUCT_USPS


PURCHASE_STAGES = ("discovery", "product", "location", "qualification", "form")

APPLICATION_FIELDS = (
    "full_name",
    "ic_number",
    "whatsapp_number",
    "email",
    "installation_address",
    "occupation",
    "company_name",
    "employment_start_date",
    "emergency_contact_name",
    "emergency_contact_phone",
    "emergency_contact_relationship",
)

APPLICATION_FIELD_LABELS = {
    "full_name": "Nama Penuh (Ikut IC)",
    "ic_number": "No IC",
    "whatsapp_number": "No Whatsapp",
    "email": "Email",
    "installation_address": "Alamat Pemasangan",
    "occupation": "Pekerjaan",
    "company_name": "Nama Syarikat",
    "employment_start_date": "Tarikh bermula",
    "emergency_contact_name": "Nama kecemasan",
    "emergency_contact_phone": "No. HP kecemasan",
    "emergency_contact_relationship": "Hubungan kecemasan",
}

_NEXT_STAGE: dict[str, str] = {
    "discovery": "product",
    "product": "location",
    "location": "qualification",
    "qualification": "form",
}


def set_product_interest(product_key: str, tool_context: ToolContext) -> dict:
    """Select a KHIND product and return its first-time fixed USP.

    Call when the customer clearly selects one product. The product key must be one
    of the keys returned by this tool when invalid. On a first selection, the
    returned USP must be used exactly once in the customer reply.
    """
    selected_product = product_key.strip().lower()
    if selected_product not in KHIND_PRODUCT_USPS:
        return {
            "status": "error",
            "message": "Invalid product key. Ask the customer to choose from the product menu.",
        }

    previous_product = tool_context.state.get("product_interest")
    pitched_products = set(tool_context.state.get("pitched_products", []))
    is_first_pitch = selected_product not in pitched_products
    tool_context.state["product_interest"] = selected_product
    if previous_product != selected_product:
        tool_context.state["rag_cache_generation"] = (
            tool_context.state.get("rag_cache_generation", 0) + 1
        )
    if tool_context.state.get("purchase_stage", "discovery") == "discovery":
        tool_context.state["purchase_stage"] = "product"

    if is_first_pitch:
        pitched_products.add(selected_product)
        tool_context.state["pitched_products"] = sorted(pitched_products)

    result = {
        "status": "ok",
        "product_interest": selected_product,
        "first_time": is_first_pitch,
    }
    if is_first_pitch:
        result["usp"] = KHIND_PRODUCT_USPS[selected_product]
        result["media_delivery"] = "trigger"
    return result


def advance_purchase_stage(tool_context: ToolContext) -> dict:
    """Advance the sales journey by exactly one valid stage.

    Call only after the customer has completed the current stage. Product selection
    is handled by set_product_interest, which moves discovery to product.
    """
    current_stage = tool_context.state.get("purchase_stage", "discovery")
    next_stage = _NEXT_STAGE.get(current_stage)
    if not next_stage:
        return {
            "status": "error",
            "message": f"Cannot advance from '{current_stage}'.",
            "current_stage": current_stage,
        }

    tool_context.state["purchase_stage"] = next_stage
    return {
        "status": "ok",
        "previous_stage": current_stage,
        "new_stage": next_stage,
    }


def mark_application_form_sent(tool_context: ToolContext) -> dict:
    """Record that the approved application form was sent to the customer.

    Call immediately before sending the fixed BORANG PERMOHONAN KHIND template.
    Do not call again once application_form_sent is true.
    """
    if tool_context.state.get("application_form_sent"):
        return {"status": "already_sent"}

    tool_context.state["application_form_sent"] = True
    return {"status": "ok", "application_form_sent": True}


def save_application_details(
    tool_context: ToolContext,
    full_name: str = "",
    ic_number: str = "",
    whatsapp_number: str = "",
    email: str = "",
    installation_address: str = "",
    occupation: str = "",
    company_name: str = "",
    employment_start_date: str = "",
    emergency_contact_name: str = "",
    emergency_contact_phone: str = "",
    emergency_contact_relationship: str = "",
) -> dict:
    """Save supplied KHIND application fields and report only missing field labels.

    Call when the customer provides one or more application fields. Never repeat
    personal values in the reply. This tool stores values privately in session state
    for later secure handoff; its result contains no personal data.
    """
    supplied = {
        "full_name": full_name,
        "ic_number": ic_number,
        "whatsapp_number": whatsapp_number,
        "email": email,
        "installation_address": installation_address,
        "occupation": occupation,
        "company_name": company_name,
        "employment_start_date": employment_start_date,
        "emergency_contact_name": emergency_contact_name,
        "emergency_contact_phone": emergency_contact_phone,
        "emergency_contact_relationship": emergency_contact_relationship,
    }
    details = dict(tool_context.state.get("application_details", {}))
    details.update(
        {field: value.strip() for field, value in supplied.items() if value.strip()}
    )
    tool_context.state["application_details"] = details

    missing_fields = [
        APPLICATION_FIELD_LABELS[field]
        for field in APPLICATION_FIELDS
        if not details.get(field)
    ]
    is_complete = not missing_fields
    tool_context.state["application_complete"] = is_complete
    return {
        "status": "complete" if is_complete else "incomplete",
        "complete": is_complete,
        "missing_fields": missing_fields,
    }
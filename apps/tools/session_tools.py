"""ADK tools that maintain the KHIND sales journey session state."""

import re

from google.adk.tools import ToolContext

from apps.prompts.khind_prompts import (
    KHIND_PRODUCT_USPS,
    LOCATION_QUESTION,
    POSTCODE_QUESTION,
    TOWN_QUESTION,
)
from apps.services.coverage import REGION_NAMES, check_coverage
from apps.services.replies import REPLY_FACTS_KEY
from apps.tools.escalation_tool import COVERAGE_HANDOFF_LABEL, hand_off


PURCHASE_STAGES = ("discovery", "product", "location", "qualification", "form")
# Stages at which the customer is still on the location step ("discovery"/"product" are
# legacy values that can already have a product).
LOCATION_STEP_STAGES = ("discovery", "product", "location")

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

PRODUCT_NUMBER_MAP: dict[str, str] = {
    "1": "chillmaster_592l",
    "2": "chillmaster_lite_480l",
    "3": "chillmaster_x_466l",
    "4": "washer_dryer_11_7",
    "5": "front_load_9kg",
    "6": "ecowash_top_15kg",
    "7": "drymaster_9kg",
    "8": "aircond_kool_series",
}

PRODUCT_ALIAS_MAP: dict[str, str] = {
    # Aircond
    "aircond": "aircond_kool_series",
    "air_conditioner": "aircond_kool_series",
    "air conditioner": "aircond_kool_series",
    "aircon": "aircond_kool_series",
    "kool": "aircond_kool_series",
    "kool series": "aircond_kool_series",
    "acson": "aircond_kool_series",
    "penyaman udara": "aircond_kool_series",
    "hawa dingin": "aircond_kool_series",
    # Peti Sejuk 592L
    "chillmaster 592l": "chillmaster_592l",
    "chillmaster 592": "chillmaster_592l",
    "592l": "chillmaster_592l",
    "592": "chillmaster_592l",
    "rsf600a": "chillmaster_592l",
    # Peti Sejuk 480L
    "chillmaster lite": "chillmaster_lite_480l",
    "chillmaster lite 480l": "chillmaster_lite_480l",
    "480l": "chillmaster_lite_480l",
    "480": "chillmaster_lite_480l",
    "rf480": "chillmaster_lite_480l",
    # Peti Sejuk 466L
    "chillmaster x": "chillmaster_x_466l",
    "chillmaster x 466l": "chillmaster_x_466l",
    "466l": "chillmaster_x_466l",
    "466": "chillmaster_x_466l",
    "rfm466a": "chillmaster_x_466l",
    # Washer Dryer 2-in-1
    "washer dryer": "washer_dryer_11_7",
    "washer & dryer": "washer_dryer_11_7",
    "washer_dryer": "washer_dryer_11_7",
    "2 in 1": "washer_dryer_11_7",
    "2-in-1": "washer_dryer_11_7",
    "wd1468": "washer_dryer_11_7",
    "mesin basuh siap kering": "washer_dryer_11_7",
    # Front Load 9KG
    "front load": "front_load_9kg",
    "front_load": "front_load_9kg",
    "front load washer": "front_load_9kg",
    "wm1248": "front_load_9kg",
    "washer 9kg": "front_load_9kg",
    # EcoWash Top Load 15KG
    "ecowash": "ecowash_top_15kg",
    "ecowash 15": "ecowash_top_15kg",
    "top load": "ecowash_top_15kg",
    "top_load": "ecowash_top_15kg",
    "wm150a": "ecowash_top_15kg",
    # DryMaster 9KG
    "drymaster": "drymaster_9kg",
    "dryer": "drymaster_9kg",
    "heat pump dryer": "drymaster_9kg",
    "dhp90": "drymaster_9kg",
    "mesin pengering": "drymaster_9kg",
}


def _resolve_product_key(raw_key: str) -> str | None:
    cleaned = (raw_key or "").strip().lower()
    if cleaned in KHIND_PRODUCT_USPS:
        return cleaned
    if cleaned in PRODUCT_NUMBER_MAP:
        return PRODUCT_NUMBER_MAP[cleaned]
    if cleaned in PRODUCT_ALIAS_MAP:
        return PRODUCT_ALIAS_MAP[cleaned]
    return None


# Aliases that name one product inside free text. Bare numbers ("592") are left out: in a
# sentence they are too often prices or sizes.
_TEXT_ALIASES: dict[str, str] = {
    **{key.replace("_", " "): key for key in KHIND_PRODUCT_USPS},
    **{alias: key for alias, key in PRODUCT_ALIAS_MAP.items() if not alias.isdigit()},
}
_TEXT_ALIAS_PATTERNS = [
    (re.compile(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"), key)
    for alias, key in sorted(_TEXT_ALIASES.items(), key=lambda item: -len(item[0]))
]


def find_product_keys(text: str) -> list[str]:
    """Return the product keys named in free text, in order of appearance.

    Longer aliases win ("washer dryer" is not also read as "dryer"). Used to limit a
    product search to the documents of the products the query names.
    """
    lowered = (text or "").lower()
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str]] = []
    for pattern, key in _TEXT_ALIAS_PATTERNS:
        for match in pattern.finditer(lowered):
            start, end = match.span()
            if any(start < t_end and t_start < end for t_start, t_end in taken):
                continue
            taken.append((start, end))
            found.append((start, key))
    keys: list[str] = []
    for _, key in sorted(found):
        if key not in keys:
            keys.append(key)
    return keys


def set_product_interest(product_key: str, tool_context: ToolContext) -> dict:
    """Select the KHIND product the customer wants.

    Call when the customer selects or names a product (canonical key, product number
    1-8, or model name), at any stage, including a product picked earlier. A first
    selection moves the journey to the location step: check a place the customer already
    gave, otherwise ask for the postcode and installation area. The system sends the
    product USP and media automatically: never write, repeat or summarise the USP yourself.
    """
    selected_product = _resolve_product_key(product_key)
    if not selected_product:
        return {
            "status": "error",
            "message": "Invalid product key. Ask the customer to choose 1-8 or from the product menu.",
        }

    previous_product = tool_context.state.get("product_interest")
    pitched_products = set(tool_context.state.get("pitched_products", []))
    is_first_pitch = selected_product not in pitched_products
    tool_context.state["product_interest"] = selected_product
    if previous_product != selected_product:
        tool_context.state["rag_cache_generation"] = (
            tool_context.state.get("rag_cache_generation", 0) + 1
        )
    # A product pick goes straight to the location step. Later stages stay put, so a
    # product switch mid-flow keeps the customer on their pending step.
    if tool_context.state.get("purchase_stage", "discovery") in ("discovery", "product"):
        tool_context.state["purchase_stage"] = "location"

    if is_first_pitch:
        pitched_products.add(selected_product)
        tool_context.state["pitched_products"] = sorted(pitched_products)
        # Read by apps.services.replies.insert_pending_usp, which puts the approved
        # USP word for word at the top of this turn's reply.
        pending_usps = list(tool_context.state.get("pending_usp_products", []))
        if selected_product not in pending_usps:
            pending_usps.append(selected_product)
        tool_context.state["pending_usp_products"] = pending_usps

    result = {
        "status": "ok",
        "product_interest": selected_product,
        "first_time": is_first_pitch,
        "purchase_stage": tool_context.state.get("purchase_stage"),
    }
    if is_first_pitch:
        result["usp_sent_automatically"] = True
        result["reply_rule"] = _first_pick_reply_rule(tool_context.state.get("purchase_stage"))
        result["media_delivery"] = "trigger"
    return result


def _first_pick_reply_rule(stage: str | None) -> str:
    rule = (
        "The system sends this product's USP and media automatically. Do not write any product "
        "description, feature list or comment about the product."
    )
    if stage == "location":
        # A place in the same message is checked now, not asked for again.
        rule += (
            " If the customer's message also gives a place (postcode, town, state or country), "
            "call advance_purchase_stage with it now."
        )
    return rule + (
        " If the customer also asked a specific question (price, spec, warranty), answer only "
        "that in 1-2 sentences using query_product_info. Apart from that, reply ONLY with the "
        "pending step's question."
    )


_ASK = {
    "need_location": LOCATION_QUESTION,
    "need_state": POSTCODE_QUESTION,
}


async def advance_purchase_stage(
    tool_context: ToolContext,
    postcode: str = "",
    town: str = "",
    state: str = "",
) -> dict:
    """Check delivery coverage for the customer's area and, if covered, move to the employment step.

    Call whenever the customer gives any location. Pass only what the customer wrote:
    postcode = the 5-digit postcode; town = the town or area name; state = the Malaysian
    state (infer it from the town, e.g. Kajang -> Selangor) or the country if outside
    Malaysia. Never work out a town from a postcode.

    Act on the returned status:
    - "ok": covered. The next instructions give the reply.
    - "not_covered": this tool has already handed the chat to an officer. Do not call
      escalate_to_live_agent; send only the not-covered line with `area`.
    - "need_town" / "need_location": no verdict yet; ask only the question in `ask`.
    - "need_state": call again with the state if you know it from the town; otherwise ask
      only the question in `ask`.
    """
    current_stage = tool_context.state.get("purchase_stage", "discovery")
    if not tool_context.state.get("product_interest"):
        return {
            "status": "error",
            "message": "No product selected yet. Ask the customer to choose a product first.",
            "current_stage": current_stage,
        }
    # The reply carries this turn's verdict or question (see insert_pending_usp).
    tool_context.state[REPLY_FACTS_KEY] = tool_context.invocation_id
    at_location_step = current_stage in LOCATION_STEP_STAGES
    if not at_location_step and not any(value.strip() for value in (postcode, town, state)):
        return {
            "status": "ok",
            "coverage": "already_confirmed",
            "message": "Coverage is already confirmed. Continue with the pending step.",
        }

    # Fill gaps from an earlier unfinished answer, so "Kapit" joins an earlier "96800".
    draft = dict(tool_context.state.get("location_draft") or {})
    postcode = postcode.strip() or draft.get("postcode", "")
    state = state.strip() or draft.get("state", "")
    verdict = check_coverage(postcode, town.strip(), state)

    if verdict.status.startswith("need_"):
        tool_context.state["location_draft"] = {"postcode": postcode, "state": state}
        ask = _ASK.get(verdict.status) or TOWN_QUESTION.format(
            region=REGION_NAMES.get(verdict.region, "Sabah/Sarawak")
        )
        return {
            "status": verdict.status,
            "ask": ask,
            "message": "No coverage verdict yet. Ask only the question in `ask`.",
        }

    tool_context.state["location_draft"] = {}
    tool_context.state["customer_location"] = verdict.location
    if verdict.status == "not_covered":
        # The handoff is made here, not left to the model: in the 2026-09-24 rerun it once
        # skipped the escalate call (B12) and once wrote its reasoning beside it (B6).
        handoff = await hand_off(COVERAGE_HANDOFF_LABEL, tool_context)
        return {
            "status": "not_covered",
            "area": verdict.area,
            "escalated": handoff["escalated"],
            "label": handoff["label"],
            "message": (
                "Area not covered. The chat is already handed to an officer: do not call "
                "escalate_to_live_agent. Reply only with the not-covered line with `area`."
            ),
        }
    if at_location_step:
        tool_context.state["purchase_stage"] = "qualification"
        return {
            "status": "ok",
            "coverage": "covered",
            "previous_stage": "location",
            "new_stage": "qualification",
            "area": verdict.area,
        }
    return {"status": "ok", "coverage": "covered", "area": verdict.area}


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
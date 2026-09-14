"""ADK entry point exposing the KHIND WhatsApp sales agent."""

from google.adk.agents import LlmAgent
from google.genai import types as genai_types

from apps.config import settings
from apps.prompts.khind_assembler import get_khind_instruction
from apps.tools.escalation_tool import escalate_to_live_agent
from apps.tools.rag_tool import query_product_info
from apps.tools.session_tools import (
	advance_purchase_stage,
	mark_application_form_sent,
	save_application_details,
	set_product_interest,
)


root_agent = LlmAgent(
	name="khind_sales_agent",
	model=settings.llm_model,
	description="KHIND Malaysia WhatsApp sales advisor.",
	instruction=get_khind_instruction,
	tools=[
		set_product_interest,
		advance_purchase_stage,
		query_product_info,
		escalate_to_live_agent,
		mark_application_form_sent,
		save_application_details,
	],
	generate_content_config=genai_types.GenerateContentConfig(
		temperature=0.3,
		max_output_tokens=800,
	),
)
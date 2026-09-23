"""ADK entry point exposing the KHIND WhatsApp sales agent."""

from google.adk.agents import LlmAgent
from google.genai import types as genai_types

from apps.config import settings
from apps.prompts.khind_assembler import get_khind_instruction
from apps.services.replies import insert_pending_usp
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
	# Puts the approved USP, word for word, above the reply after a first product pick.
	after_model_callback=insert_pending_usp,
	generate_content_config=genai_types.GenerateContentConfig(
		temperature=0.3,
		# Gemini 2.5 counts thinking tokens against max_output_tokens; cap thinking so
		# long replies such as the BORANG are never cut off.
		max_output_tokens=2048,
		thinking_config=genai_types.ThinkingConfig(thinking_budget=1024),
	),
)
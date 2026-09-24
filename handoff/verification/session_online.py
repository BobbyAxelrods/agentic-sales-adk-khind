"""Online check of the session layer on the real Agent Engine (VERTEX_AI_AGENT_ENGINE_ID).

Runs two real Gemini turns ("hai", then "8") on a new test session, writes a state patch,
reads everything back through a second session service (another Cloud Run instance), and
deletes the test session. Chatwoot is switched off, so nothing is sent to any customer.

Run from the repo root: .venv/bin/python handoff/verification/session_online.py
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv(".env")
os.environ["CHATWOOT_BASE_URL"] = ""  # no Chatwoot calls from tools or the webhook

from google.adk.sessions import VertexAiSessionService

import apps.runner as rn
from apps.config import settings
from apps.prompts.khind_prompts import KHIND_PRODUCT_USPS, LOCATION_QUESTION, PRODUCT_MENU

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)


async def main():
    check(isinstance(rn.session_service, VertexAiSessionService) and settings.vertex_ai_agent_engine_id,
          f"the webhook uses Agent Engine {settings.vertex_ai_agent_engine_id}")
    conversation_id = f"selftest-{int(time.time())}"
    sid = rn.session_id_for(conversation_id)
    try:
        t0 = time.monotonic()
        state = await rn.ensure_session(sid, conversation_id)
        check(state.get("chatwoot_conversation_id") == conversation_id and state.get("purchase_stage") == "discovery",
              f"session {sid} created in {time.monotonic() - t0:.1f}s with the default state")

        t0 = time.monotonic()
        reply, state = await rn.run_turn(sid, "hai", {"webhook_selftest": True})
        print(f"   turn 1 ({time.monotonic() - t0:.1f}s): {reply[:160]!r}")
        check(reply and not reply.startswith("Maaf, sistem") and state.get("webhook_selftest") is True,
              "turn 1 ran on the stored session and kept the message's state delta")
        check(reply.count(PRODUCT_MENU) == 1, "turn 1: the greeting carries the product list once")

        t0 = time.monotonic()
        reply, state = await rn.run_turn(sid, "8")
        product = state.get("product_interest")
        print(f"   turn 2 ({time.monotonic() - t0:.1f}s): {reply[:160]!r}")
        check(product in KHIND_PRODUCT_USPS and state.get("purchase_stage") == "location",
              f"turn 2 picked {product} and moved to the location step (tool state is stored)")
        check(reply.startswith(KHIND_PRODUCT_USPS[product]) and LOCATION_QUESTION in reply,
              "turn 2 reply: the approved USP on top, then the location question")

        await rn.patch_session_state(sid, {"initial_media_sent_products": [product]})

        other = VertexAiSessionService(project=settings.google_cloud_project,
                                       location=settings.google_cloud_location,
                                       agent_engine_id=settings.vertex_ai_agent_engine_id)
        t0 = time.monotonic()
        stored = await other.get_session(app_name=rn.APP_NAME, user_id=sid, session_id=sid)
        load_time = time.monotonic() - t0
        texts = [p.text for e in stored.events if e.author == "user" and e.content for p in e.content.parts if p.text]
        check(stored.state.get("product_interest") == product
              and stored.state.get("initial_media_sent_products") == [product],
              "a second session service reads the turn's state and the patch")
        check(texts == ["hai", "8"],
              f"the store holds the conversation ({len(stored.events)} events, loaded in {load_time:.1f}s)")
    finally:
        await rn.session_service.delete_session(app_name=rn.APP_NAME, user_id=sid, session_id=sid)
        gone = await rn.get_session_state(sid)
        print(f"   test session deleted: {gone == {}}")

    print(f"\nALL {ok} ONLINE SESSION CHECKS PASSED")


asyncio.run(main())

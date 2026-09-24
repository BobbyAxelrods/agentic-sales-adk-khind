"""Offline checks for the webhook's session layer (apps/runner.py), on the in-memory store.

A stub agent replaces Gemini. The checks cover: the session ID format that Agent Engine
accepts, session creation, state writes outside a turn, state sent with a message, and
that a second Runner on the same store (another Cloud Run instance) sees every change.

Run from the repo root: .venv/bin/python handoff/verification/session_checks.py
"""
import asyncio
import os
import re
import sys

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv(".env")  # the agent's tools build GCS and Vertex AI clients on import
os.environ["VERTEX_AI_AGENT_ENGINE_ID"] = ""  # force the in-memory store

from google.adk.agents import BaseAgent
from google.adk.events import Event, EventActions
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as T

import apps.runner as rn

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)


class StubAgent(BaseAgent):
    """Replies "reply N" and counts its turns in state, like a tool writing state."""

    async def _run_async_impl(self, ctx):
        turns = ctx.session.state.get("turns", 0) + 1
        yield Event(
            invocation_id=ctx.invocation_id,
            author=self.name,
            content=T.Content(role="model", parts=[T.Part(text=f"reply {turn_text(ctx, turns)}")]),
            actions=EventActions(state_delta={"turns": turns}),
        )


def turn_text(ctx, turns):
    return f"{turns} language={ctx.session.state.get('language')}"


def stub_runner(service):
    return Runner(agent=StubAgent(name=rn.root_agent.name), app_name=rn.APP_NAME, session_service=service)


# Agent Engine: up to 63 characters of [a-z0-9-], starting with a letter, ending with a
# letter or digit.
AGENT_ENGINE_ID = re.compile(r"^[a-z][a-z0-9-]{0,61}[a-z0-9]$")


async def main():
    check(isinstance(rn.session_service, InMemorySessionService),
          "no VERTEX_AI_AGENT_ENGINE_ID: the in-memory store is used")
    check(not hasattr(rn, "_memory") and not hasattr(rn, "_loaded"),
          "no per-instance session cache is left in apps.runner")

    sid = rn.session_id_for("12345")
    check(sid == "conv-12345" and AGENT_ENGINE_ID.match(sid),
          f"session ID {sid!r} is valid for Agent Engine (no underscore)")

    check(await rn.get_session_state(sid) == {}, "unknown session: empty state")
    state = await rn.ensure_session(sid, "12345")
    check(state.get("purchase_stage") == "discovery" and state.get("chatwoot_conversation_id") == "12345",
          "first message creates the session with the default state and the conversation ID")
    await rn.patch_session_state(sid, {"language": "ms"})
    again = await rn.ensure_session(sid, "12345")
    check(again.get("language") == "ms" and again.get("purchase_stage") == "discovery",
          "a later message keeps the stored state (patch outside a turn is stored)")

    rn.runner = stub_runner(rn.session_service)
    reply, after = await rn.run_turn(sid, "hai", state_delta={"escalated": False, "escalation_label": None})
    check(reply == "reply 1 language=ms", f"the turn sees state written before it: {reply!r}")
    check(after.get("turns") == 1 and after.get("escalated") is False,
          "state after the turn has the agent's change and the message's state delta")

    # Another Cloud Run instance: its own Runner on the same store.
    other = stub_runner(rn.session_service)
    events = [e async for e in other.run_async(
        user_id=sid, session_id=sid, new_message=T.Content(role="user", parts=[T.Part(text="lagi")]))]
    check(events and events[-1].content.parts[0].text == "reply 2 language=ms",
          "a second Runner on the same store continues the same session")
    check((await rn.get_session_state(sid)).get("turns") == 2,
          "the first instance reads the second instance's change from the store")

    await rn.patch_session_state(sid, {"initial_media_sent_products": ["aircond_kool_series"]})
    stored = await rn.session_service.get_session(app_name=rn.APP_NAME, user_id=sid, session_id=sid)
    check(stored.state.get("initial_media_sent_products") == ["aircond_kool_series"],
          "a patch is an event with a state delta, so the store applies it")
    check(all(not (e.content and e.content.parts) for e in stored.events if e.author == "user" and e.actions.state_delta
              and "initial_media_sent_products" in e.actions.state_delta),
          "the patch event carries no content, so the model never sees it")

    rn.runner = stub_runner(InMemorySessionService())  # a store that does not know the session
    reply, after = await rn.run_turn(sid, "hai")
    check(reply.startswith("Maaf, sistem") and after == {},
          "a failing turn returns the technical-problem line and no state")

    print(f"\nALL {ok} SESSION CHECKS PASSED")


asyncio.run(main())

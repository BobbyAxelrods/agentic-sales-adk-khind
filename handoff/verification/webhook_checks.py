"""Offline checks for the Chatwoot webhook (apps/webhook.py) and the Chatwoot client.

The app runs in-process through httpx's ASGI transport; the session layer, the model turn,
media and Chatwoot sends are fakes that log their calls. Covered: the signature check,
the event filter, repeats, the immediate 200 with the turn in the background, one turn at
a time per conversation, send order, the IC photos after the form, the resume after a
handoff, and the Chatwoot label and status calls.

Run from the repo root: .venv/bin/python handoff/verification/webhook_checks.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time

sys.path.insert(0, ".")
from dotenv import load_dotenv

load_dotenv(".env")  # the agent's tools build GCS and Vertex AI clients on import
os.environ["VERTEX_AI_AGENT_ENGINE_ID"] = ""  # never touch the real session store

import httpx

import apps.clients.chatwoot as cw
import apps.webhook as wh
from apps.main import app
from apps.prompts.khind_prompts import IC_PHOTOS_RECEIVED_LINE

SECRET = "test-webhook-secret"
wh.settings.chatwoot_webhook_secret = SECRET
wh.settings.chatwoot_base_url = ""  # an unfaked Chatwoot call is a no-op, never a real send

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

calls: list = []
STATE: dict = {}          # stored state before the turn
TURN = {"reply": "USP + soalan", "after": {}, "delay": 0.0}
LIVE = {"status": "pending"}
MEDIA = {"delay": 0.0}

async def fake_ensure_session(session_id, conversation_id):
    calls.append(("ensure", session_id))
    return dict(STATE)

async def fake_run_turn(session_id, text, state_delta=None):
    calls.append(("turn_start", text, state_delta))
    await asyncio.sleep(TURN["delay"])
    calls.append(("turn_end", text))
    return TURN["reply"], {**STATE, **(state_delta or {}), **TURN["after"]}

async def fake_patch(session_id, updates):
    calls.append(("patch", updates))

async def fake_media(conversation_id, product_key, state, session_id):
    calls.append("media_start")
    await asyncio.sleep(MEDIA["delay"])
    calls.append("media_done")

async def fake_send_text(cid, text): calls.append(("text", text))
async def fake_escalate(cid, label, state):
    calls.append(("escalate", label))
    return True
async def fake_status(cid):
    calls.append("status_check")
    return LIVE["status"]

real_deliver_media = wh._deliver_media
wh.ensure_session = fake_ensure_session
wh.run_turn = fake_run_turn
wh.patch_session_state = fake_patch
wh._deliver_media = fake_media
wh.chatwoot.send_text = fake_send_text
wh.chatwoot.escalate_conversation = fake_escalate
wh.chatwoot.get_conversation_status = fake_status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_next_id = iter(range(1000, 100000))

def payload(content="hai", *, event="message_created", message_type="incoming", private=False,
            status="pending", conv=42, mid=None, attachments=None):
    """A Chatwoot agent-bot message payload (Message#webhook_data plus "event")."""
    p = {
        "event": event, "id": next(_next_id) if mid is None else mid, "content": content,
        "message_type": message_type, "private": private, "content_type": "text",
        "content_attributes": {}, "account": {"id": 1}, "inbox": {"id": 2},
        "sender": {"id": 7, "name": "Pelanggan"}, "conversation": {"id": conv, "status": status},
    }
    if attachments:
        p["attachments"] = attachments
    return p

IMAGE = [{"id": 5, "file_type": "image", "data_url": "https://chatwoot.test/ic.jpg"}]

def sign(body, secret=SECRET, ts=None):
    ts = str(int(time.time()) if ts is None else ts)
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Chatwoot-Timestamp": ts, "X-Chatwoot-Signature": f"sha256={digest}",
            "Content-Type": "application/json"}

async def drain():
    while wh._background_tasks:
        await asyncio.gather(*list(wh._background_tasks), return_exceptions=True)

async def post(client, p, headers=None, body=None):
    body = json.dumps(p).encode() if body is None else body
    return await client.post("/webhook", content=body, headers=sign(body) if headers is None else headers)

def reset(state=None, reply="USP + soalan", after=None, delay=0.0, live="pending", media_delay=0.0):
    calls.clear()
    STATE.clear(); STATE.update(state or {})
    TURN.update(reply=reply, after=after or {}, delay=delay)
    LIVE["status"] = live
    MEDIA["delay"] = media_delay

def kinds():
    return [c if isinstance(c, str) else c[0] for c in calls]


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

async def signature_checks(client):
    body = json.dumps(payload()).encode()
    reset()
    r = await post(client, None, body=body)
    await drain()
    check(r.status_code == 200 and r.json() == {"status": "accepted"} and "turn_start" in kinds(),
          "a correctly signed customer message is accepted and runs a turn")
    bad = [
        ("a wrong signature", sign(body, secret="other-secret")),
        ("a timestamp older than 5 minutes", sign(body, ts=int(time.time()) - 301)),
        ("a timestamp more than 5 minutes ahead", sign(body, ts=int(time.time()) + 301)),
        ("no signature headers", {"Content-Type": "application/json"}),
        ("a non-numeric timestamp", {**sign(body), "X-Chatwoot-Timestamp": "abc"}),
    ]
    for name, headers in bad:
        reset()
        r = await post(client, None, headers=headers, body=body)
        await drain()
        check(r.status_code == 401 and calls == [], f"401 and no work for {name}")
    reset()
    signed = sign(body)
    tampered = body.replace(b'"hai"', b'"hi!"')
    r = await post(client, None, headers=signed, body=tampered)
    check(r.status_code == 401 and calls == [], "401 when the body changed after signing")
    wh.settings.chatwoot_webhook_secret = ""
    reset()
    r = await post(client, None, headers=sign(body, secret=""), body=body)
    wh.settings.chatwoot_webhook_secret = SECRET
    check(r.status_code == 401 and calls == [], "401 for every call while CHATWOOT_WEBHOOK_SECRET is unset")


async def filter_checks(client):
    ignored = [
        ("the bot's or an officer's reply (outgoing)", payload(message_type="outgoing")),
        ("a private note", payload(private=True)),
        ("an activity message", payload(message_type="activity")),
        ("a template message", payload(message_type="template")),
        ("a WhatsApp delivered/read update (message_updated)", payload(event="message_updated")),
        ("a status event", {"event": "conversation_status_changed", "id": 42, "status": "open"}),
        ("a chat an officer has (open)", payload(status="open")),
        ("a resolved chat", payload(status="resolved")),
        ("a snoozed chat", payload(status="snoozed")),
        ("a message with no conversation", {**payload(), "conversation": None}),
        ("a message with no text and no image (e.g. a voice note)",
         payload(content=None, attachments=[{"id": 9, "file_type": "audio"}])),
        ("an image before the application is complete", payload(content=None, attachments=IMAGE)),
    ]
    for name, p in ignored:
        reset()
        r = await post(client, p)
        await drain()
        check(r.status_code == 200 and [k for k in kinds() if k != "ensure"] == [],
              f"200 and no reply for {name}")


async def repeat_and_background_checks(client):
    reset()
    p = payload(mid=777)
    r1 = await post(client, p)
    r2 = await post(client, p)
    await drain()
    check(r1.json() == {"status": "accepted"} and r2.json() == {"status": "duplicate"}
          and kinds().count("turn_start") == 1, "a repeated message ID (Chatwoot retry) runs one turn")

    reset(delay=0.5)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    r = await post(client, payload())
    returned_after = loop.time() - t0
    finished_before_reply = "turn_end" in kinds()
    await drain()
    check(r.status_code == 200 and returned_after < 0.25 and not finished_before_reply,
          f"200 comes back before the turn ends ({returned_after:.2f}s for a 0.5s turn)")

    reset(delay=0.2)
    await post(client, payload("satu", conv=50))
    await post(client, payload("dua", conv=50))
    await drain()
    order = [(c[0], c[1]) for c in calls if not isinstance(c, str) and c[0] in ("turn_start", "turn_end")]
    check(order == [("turn_start", "satu"), ("turn_end", "satu"), ("turn_start", "dua"), ("turn_end", "dua")],
          "two messages in one chat: one turn at a time, in arrival order")

    reset(delay=0.2)
    await post(client, payload("A", conv=60))
    await post(client, payload("B", conv=61))
    await drain()
    order = [(c[0], c[1]) for c in calls if not isinstance(c, str) and c[0] in ("turn_start", "turn_end")]
    check(order[:2] == [("turn_start", "A"), ("turn_start", "B")], "two chats run their turns at the same time")
    check(not wh._conversation_locks, "no per-chat lock is left once the chats are idle")


async def order_checks(client):
    reset(state={"purchase_stage": "discovery"})
    await post(client, payload("hai"))
    await drain()
    check(kinds() == ["ensure", "turn_start", "turn_end", "text"] and not hasattr(wh.chatwoot, "send_product_list"),
          f"first message: turn, then text; the model's greeting carries the product list: {kinds()}")

    reset(state={"purchase_stage": "discovery"},
          after={"product_interest": "aircond_kool_series", "purchase_stage": "location"})
    await post(client, payload("8"))
    await drain()
    check(kinds() == ["ensure", "turn_start", "turn_end", "media_start", "media_done", "text"],
          f"product pick: media, then text: {kinds()}")
    check(not hasattr(wh.chatwoot, "set_conversation_pending"),
          "no pending toggles: bot-token sends never change the chat status")

    reset(state={"product_interest": "aircond_kool_series", "purchase_stage": "location"},
          after={"escalated": True, "escalation_label": "coverage-unsupported-alternative"})
    await post(client, payload("88000 Kota Kinabalu"))
    await drain()
    check(kinds() == ["ensure", "turn_start", "turn_end", "text"], f"a handoff turn: text only, no media: {kinds()}")

    reset(state={"purchase_stage": "discovery"}, after={"product_interest": "aircond_kool_series"},
          media_delay=0.6)
    wh._MEDIA_WAIT_SECONDS = 0.2
    await post(client, payload("8"))
    await asyncio.sleep(0.35)
    at_bound = kinds()
    await drain()
    wh._MEDIA_WAIT_SECONDS = 20.0
    check(at_bound[-2:] == ["media_start", "text"] and kinds()[-1] == "media_done",
          f"slow media: the text goes at the bound, the upload finishes later: {kinds()}")

    reset(state={"purchase_stage": "discovery"}, reply="")
    await post(client, payload("..."))
    await drain()
    check(kinds() == ["ensure", "turn_start", "turn_end"], "an empty reply sends nothing")


async def ic_photo_checks(client):
    done = {"purchase_stage": "form", "application_complete": True, "product_interest": "aircond_kool_series"}
    for name, p in [("an image", payload(content=None, attachments=IMAGE)),
                    ("an image with a caption", payload("ni IC saya", attachments=IMAGE))]:
        reset(state=done)
        await post(client, p)
        await drain()
        check(kinds() == ["ensure", "escalate", "text", "patch"] and calls[1] == ("escalate", "human-required")
              and calls[2] == ("text", IC_PHOTOS_RECEIVED_LINE)
              and calls[3] == ("patch", {"escalated": True, "escalation_label": "human-required"}),
              f"{name} after the form: handoff (human-required), the fixed line, state saved; no model turn")


async def resume_checks(client):
    handed = {"escalated": True, "escalation_label": "not-working", "purchase_stage": "qualification",
              "product_interest": "aircond_kool_series"}
    reset(state=handed, live="pending")
    await post(client, payload("hai lagi"))
    await drain()
    turn = next((c for c in calls if not isinstance(c, str) and c[0] == "turn_start"), None)
    check(kinds()[:2] == ["ensure", "status_check"] and turn is not None
          and turn[2] == {"escalated": False, "escalation_label": None},
          "a chat given back to the bot (still pending): the handoff flag is cleared and the turn runs")

    reset(state=handed, live="open")
    await post(client, payload("hai lagi"))
    await drain()
    check(kinds() == ["ensure", "status_check"],
          "a message queued behind the handoff turn (chat now open): no turn, no reply")

    reset(state=handed, live=None)
    await post(client, payload("hai lagi"))
    await drain()
    check("turn_start" in kinds(), "the live status is unknown (API error): the payload's pending status is used")


async def media_checks():
    def fake_plan(product_key, state):
        sent = set(state.get("initial_media_sent_products", []))
        if product_key in sent:
            return {"status": "already_sent", "media": []}
        state["initial_media_sent_products"] = sorted(sent | {product_key})
        return {"status": "ok", "media": [{"gcs_uri": f"gs://b/{product_key}/{n}"} for n in ("1.jpeg", "2.jpeg", "3.mp4")]}

    async def fake_attachment(cid, data, filename, content_type):
        calls.append(("upload", filename))

    wh.get_initial_media_plan = fake_plan
    wh.download_bytes = lambda uri: (b"x", "image/jpeg")
    wh.chatwoot.send_attachment = fake_attachment
    reset()
    await real_deliver_media("42", "aircond_kool_series", {"initial_media_sent_products": []}, "conv-42")
    check(calls[0] == ("patch", {"initial_media_sent_products": ["aircond_kool_series"]})
          and sorted(c[1] for c in calls[1:]) == ["1.jpeg", "2.jpeg", "3.mp4"],
          "first pick of a product: marked as sent in the session, then 2 images and 1 video")
    reset()
    await real_deliver_media("42", "aircond_kool_series", {"initial_media_sent_products": ["aircond_kool_series"]}, "conv-42")
    check(calls == [], "a product already sent: no upload and no session write")


async def chatwoot_client_checks():
    requests = []
    labels_now = {"payload": ["vip"]}

    def handler(request):
        requests.append((request.method, request.url.path, json.loads(request.content or b"null")))
        if request.method == "GET" and request.url.path.endswith("/labels"):
            return httpx.Response(200, json=labels_now)
        if request.method == "GET":
            return httpx.Response(200, json={"id": 42, "status": "open"})
        if request.url.path.endswith("/messages"):
            return httpx.Response(500, json={})
        return httpx.Response(200, json={})

    saved = (wh.settings.chatwoot_base_url, wh.settings.chatwoot_api_token, wh.settings.chatwoot_account_id,
             wh.settings.chatwoot_human_agent_id)
    wh.settings.chatwoot_base_url, wh.settings.chatwoot_api_token = "https://chatwoot.test", "t"
    wh.settings.chatwoot_account_id, wh.settings.chatwoot_human_agent_id = "1", "9"
    cw._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = cw.ChatwootClient()
    try:
        opened = await client.escalate_conversation("42", "not-working", {"purchase_stage": "qualification"})
        posts = {path.rsplit("/", 1)[-1]: body for method, path, body in requests if method == "POST"}
        check(requests[0][:2] == ("POST", "/api/v1/accounts/1/conversations/42/toggle_status")
              and requests[0][2] == {"status": "open"}, "a handoff opens the chat first")
        check(posts["labels"] == {"labels": ["vip", "not-working"]},
              "the handoff label is added to the chat's labels, not put in their place")
        check(posts["assignments"] == {"assignee_id": 9} and opened is True,
              "the chat is assigned; a failed private note is logged but the handoff stands")

        requests.clear()
        check(await client.get_conversation_status("42") == "open"
              and requests == [("GET", "/api/v1/accounts/1/conversations/42", None)],
              "the live chat status is read from the conversation")
    finally:
        await cw._http.aclose()
        cw._http = None
        (wh.settings.chatwoot_base_url, wh.settings.chatwoot_api_token, wh.settings.chatwoot_account_id,
         wh.settings.chatwoot_human_agent_id) = saved


async def main():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        await signature_checks(client)
        await filter_checks(client)
        await repeat_and_background_checks(client)
        await order_checks(client)
        await ic_photo_checks(client)
        await resume_checks(client)
    await media_checks()
    # The fakes replaced these methods on the shared client instance; the client checks
    # below use a fresh ChatwootClient with the real methods.
    await chatwoot_client_checks()
    print(f"\nALL {ok} WEBHOOK CHECKS PASSED")


asyncio.run(main())

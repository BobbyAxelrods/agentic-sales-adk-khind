"""Replay signed Chatwoot webhook calls against the app on a local port, end to end.

Starts a mock Chatwoot API that records every call, then the app (uvicorn) with
CHATWOOT_BASE_URL pointing at the mock and a test webhook secret. Everything else is real:
the signature check, the event filter, the background turn with Gemini, the Agent Engine
session store (VERTEX_AI_AGENT_ENGINE_ID in .env) and the media from GCS. Nothing reaches
the real Chatwoot. The test session is deleted at the end.

Steps: "hai" (greeting and list), "8" (media, then USP and location question), events the
bot must ignore, a bad signature, a repeated delivery, an uncovered area (handoff), a
message while an officer has the chat, and the resume when the chat is pending again.

Run from the repo root: .venv/bin/python handoff/verification/replay_local.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import secrets
import socket
import sys
import threading
import time

sys.path.insert(0, ".")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MOCK_PORT, APP_PORT = free_port(), free_port()
SECRET = secrets.token_urlsafe(18)
os.environ.update({
    "CHATWOOT_BASE_URL": f"http://127.0.0.1:{MOCK_PORT}",
    "CHATWOOT_API_TOKEN": "mock-token",
    "CHATWOOT_ACCOUNT_ID": "1",
    "CHATWOOT_WEBHOOK_SECRET": SECRET,
    "CHATWOOT_HUMAN_AGENT_ID": "9",
})
from dotenv import load_dotenv

load_dotenv(".env")  # GCP project, model, corpus, bucket, engine; the values above win

import httpx
import uvicorn
from fastapi import FastAPI, Request
from google.adk.sessions import VertexAiSessionService

from apps.config import settings
from apps.main import app
from apps.prompts.khind_prompts import KHIND_PRODUCT_USPS, LOCATION_QUESTION, PRODUCT_MENU
from apps.runner import APP_NAME, session_id_for

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)


# ---------------------------------------------------------------------------
# Mock Chatwoot API (the calls the bot makes with an agent bot token)
# ---------------------------------------------------------------------------

mock = FastAPI()
LOG: list[dict] = []
STATUS: dict[str, str] = {}
LABELS: dict[str, list] = {}
CONV = "/api/v1/accounts/1/conversations/{cid}"


@mock.get(CONV)
async def show(cid: str):
    return {"id": int(cid), "status": STATUS.get(cid, "pending")}


@mock.post(CONV + "/toggle_status")
async def toggle_status(cid: str, request: Request):
    STATUS[cid] = (await request.json())["status"]
    LOG.append({"call": "toggle_status", "status": STATUS[cid]})
    return {"payload": {"success": True, "current_status": STATUS[cid]}}


@mock.get(CONV + "/labels")
async def labels_index(cid: str):
    return {"payload": LABELS.get(cid, [])}


@mock.post(CONV + "/labels")
async def labels_create(cid: str, request: Request):
    LABELS[cid] = (await request.json())["labels"]
    LOG.append({"call": "labels", "labels": LABELS[cid]})
    return {"payload": LABELS[cid]}


@mock.post(CONV + "/assignments")
async def assignments(cid: str, request: Request):
    LOG.append({"call": "assignment", **(await request.json())})
    return {}


@mock.post(CONV + "/messages")
async def messages(cid: str, request: Request):
    if request.headers.get("content-type", "").startswith("multipart/"):
        upload = (await request.form())["attachments[]"]
        LOG.append({"call": "attachment", "filename": upload.filename, "bytes": len(await upload.read())})
    else:
        body = await request.json()
        LOG.append({"call": "note" if body.get("private") else "text", "content": body["content"]})
    return {"id": len(LOG)}


def serve(asgi_app, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(asgi_app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


# ---------------------------------------------------------------------------
# Webhook calls
# ---------------------------------------------------------------------------

CONVERSATION = str(900000 + int(time.time()) % 100000)
_ids = iter(range(int(time.time()) * 10, int(time.time()) * 10 + 10000))


def event(content, *, event_name="message_created", message_type="incoming", private=False,
          status="pending", mid=None):
    return {
        "event": event_name, "id": next(_ids) if mid is None else mid, "content": content,
        "message_type": message_type, "private": private, "content_type": "text", "content_attributes": {},
        "account": {"id": 1}, "inbox": {"id": 2}, "sender": {"id": 7, "name": "Replay"},
        "conversation": {"id": int(CONVERSATION), "status": status},
    }


def signed_headers(body: bytes, secret: str = SECRET) -> dict:
    ts = str(int(time.time()))
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return {"X-Chatwoot-Timestamp": ts, "X-Chatwoot-Signature": f"sha256={digest}",
            "Content-Type": "application/json"}


async def send(client, payload, secret=SECRET):
    body = json.dumps(payload, separators=(",", ":")).encode()
    r = await client.post("/webhook", content=body, headers=signed_headers(body, secret))
    return r.status_code, (r.json() if r.status_code == 200 else None)


async def next_text(start: int, timeout: float = 90.0) -> tuple[str, list[dict]]:
    """Wait for the next customer text after LOG[start]; return it and the calls up to it."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for i in range(start, len(LOG)):
            if LOG[i]["call"] == "text":
                return LOG[i]["content"], LOG[start:i + 1]
        await asyncio.sleep(0.2)
    raise AssertionError(f"no reply within {timeout:.0f}s; calls: {LOG[start:]}")


async def main():
    mock_server, app_server = serve(mock, MOCK_PORT), serve(app, APP_PORT)
    sid = session_id_for(CONVERSATION)
    print(f"   mock Chatwoot :{MOCK_PORT}, app :{APP_PORT}, conversation {CONVERSATION} (session {sid})")
    try:
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{APP_PORT}", timeout=10) as client:
            t0 = time.monotonic()
            status, body = await send(client, event("hai"))
            answered = time.monotonic() - t0
            text, calls = await next_text(0)
            check(status == 200 and body == {"status": "accepted"} and answered < 1.0,
                  f"'hai' accepted in {answered:.2f}s (Chatwoot waits 5 s)")
            check([c["call"] for c in calls] == ["text"] and text.count(PRODUCT_MENU) == 1,
                  "'hai': one message, the greeting with the product list once")

            start = len(LOG)
            pick = event("8")
            status, body = await send(client, pick)
            text, calls = await next_text(start)
            files = [c["filename"] for c in calls if c["call"] == "attachment"]
            check([c["call"] for c in calls] == ["attachment"] * 3 + ["text"]
                  and sorted(f.rsplit(".", 1)[-1] for f in files) == ["jpeg", "jpeg", "mp4"],
                  f"'8': 2 images and 1 video, then the text ({files})")
            check(text.startswith(KHIND_PRODUCT_USPS["aircond_kool_series"]) and LOCATION_QUESTION in text,
                  "'8': the approved USP on top, then the location question")

            start = len(LOG)
            ignored = [
                event(text, message_type="outgoing"),
                event("nota dalaman", message_type="outgoing", private=True),
                event(text, event_name="message_updated", message_type="outgoing"),
                {"event": "conversation_status_changed", "id": int(CONVERSATION), "status": "pending"},
            ]
            results = [await send(client, p) for p in ignored]
            bad_sig = await send(client, event("hai"), secret="wrong-secret")
            repeat = await send(client, pick)
            await asyncio.sleep(2)
            check(all(r == (200, {"status": "ignored"}) for r in results) and len(LOG) == start,
                  "the bot's own reply, a private note, a delivered/read update and a status event: ignored")
            check(bad_sig == (401, None) and repeat == (200, {"status": "duplicate"}) and len(LOG) == start,
                  "a wrong signature gets 401, a repeated delivery runs nothing")

            start = len(LOG)
            await send(client, event("Saya di Kapit, Sarawak. Poskod 96800"))
            text, calls = await next_text(start)
            kinds = [c["call"] for c in calls]
            check(kinds[0] == "toggle_status" and calls[0]["status"] == "open" and "attachment" not in kinds
                  and {"labels", "note", "assignment"} <= set(kinds) and kinds[-1] == "text",
                  f"uncovered area: chat opened, labelled, noted and assigned, then the reply ({kinds})")
            check(LABELS[CONVERSATION] == ["coverage-unsupported-alternative"]
                  and "Kapit" in text and "belum ada liputan" in text,
                  "uncovered area: the coverage label and the 'nanti' line with the area")

            start = len(LOG)
            status, body = await send(client, event("hello?", status="open"))
            await asyncio.sleep(2)
            check(body == {"status": "ignored"} and len(LOG) == start,
                  "while an officer has the chat (open): no reply")

            STATUS[CONVERSATION] = "pending"  # resolved, then the customer wrote again
            start = len(LOG)
            await send(client, event("Saya dah pindah ke Kajang, Selangor"))
            text, calls = await next_text(start)
            print(f"   resume reply: {text[:200]!r}")
            check([c["call"] for c in calls] == ["text"] and "bekerja sekarang" in text,
                  "chat pending again: the bot resumes the flow (Kajang covered, then the kerja question)")
    finally:
        app_server.should_exit = mock_server.should_exit = True
        service = VertexAiSessionService(project=settings.google_cloud_project,
                                         location=settings.google_cloud_location,
                                         agent_engine_id=settings.vertex_ai_agent_engine_id)
        try:
            await service.delete_session(app_name=APP_NAME, user_id=sid, session_id=sid)
            print(f"   test session {sid} deleted")
        except Exception as exc:
            print(f"   could not delete test session {sid}: {exc}")

    print(f"\nALL {ok} LOCAL REPLAY CHECKS PASSED")


asyncio.run(main())

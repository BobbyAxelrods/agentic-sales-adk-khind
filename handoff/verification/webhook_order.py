"""Check webhook send order: media, then text, then pending (and the 20 s bound).

Run from the repo root: .venv/bin/python handoff/verification/webhook_order.py
"""
import asyncio, sys
sys.path.insert(0, ".")
from dotenv import load_dotenv
load_dotenv(".env")  # importing the webhook builds a GCS client
import apps.webhook as wh

calls = []
MEDIA_DELAY = 0.0

async def fake_media(conversation_id, product_key, state, session_id):
    calls.append("media_start")
    await asyncio.sleep(MEDIA_DELAY)
    calls.append("media_done")

async def fake_send_text(cid, text): calls.append("text")
async def fake_pending(cid): calls.append("pending")
async def fake_escalate_check(cid, state): calls.append("escalate_check")
async def noop(*a, **k): return None

TURN = {}
async def fake_run_turn(session_id, message):
    return TURN["reply"], TURN["state"]

wh.run_turn = fake_run_turn
wh._deliver_media = fake_media
wh.patch_session_state = lambda *a, **k: None
wh.get_session_state = lambda *a, **k: {}
wh._maybe_send_catalog = noop
wh._maybe_escalate = fake_escalate_check
wh.resolve_product_selection = lambda row: "aircond_kool_series"
wh.chatwoot.send_text = fake_send_text
wh.chatwoot.set_conversation_pending = fake_pending

class Req:
    def __init__(self, payload): self.payload = payload
    async def json(self): return self.payload

ROUTE_A = {"conversation": {"id": 42}, "content_attributes": {"item": {"id": "row_8"}}}
ROUTE_B = {"conversation": {"id": 42}, "content": "8"}

async def run(payload, reply="USP + soalan", state=None, delay=0.0, bound=None):
    global MEDIA_DELAY
    MEDIA_DELAY = delay
    if bound is not None:
        wh._MEDIA_WAIT_SECONDS = bound
    calls.clear()
    TURN["reply"], TURN["state"] = reply, (state if state is not None else {"product_interest": "aircond_kool_series"})
    await wh.webhook(Req(payload))
    at_return = list(calls)
    if wh._background_tasks:
        await asyncio.gather(*wh._background_tasks)
    return at_return, list(calls)

async def main():
    r, _ = await run(ROUTE_A)
    assert r == ["media_start", "media_done", "text", "pending"], r
    print("PASS route A order:", r)
    r, _ = await run(ROUTE_B)
    assert r == ["media_start", "media_done", "text", "pending", "escalate_check"], r
    print("PASS route B order:", r)
    r, _ = await run(ROUTE_B, state={"product_interest": "aircond_kool_series", "escalated": True})
    assert "pending" not in r and r.index("media_done") < r.index("text"), r
    print("PASS route B escalated, no pending:", r)
    r, _ = await run(ROUTE_B, state={})
    assert r == ["text", "pending", "escalate_check"], r
    print("PASS route B no product, no media:", r)
    loop = asyncio.get_running_loop(); t0 = loop.time()
    r, final = await run(ROUTE_B, delay=1.0, bound=0.3)
    waited = loop.time() - t0
    assert r == ["media_start", "text", "pending", "escalate_check"], r
    assert final[-2:] == ["media_done", "pending"], final
    print(f"PASS slow media: text at the bound, late upload then re-pends: {final} ({waited:.1f}s total)")
    r, final = await run(ROUTE_B, delay=1.0, bound=0.3, state={"product_interest": "aircond_kool_series", "escalated": True})
    assert "pending" not in final and final[-1] == "media_done", final
    print(f"PASS slow media after handoff: no re-pend: {final}")
    r, final = await run(ROUTE_A, delay=1.0, bound=0.3)
    assert r == ["media_start", "text", "pending"] and final[-2:] == ["media_done", "pending"], final
    print(f"PASS route A slow media re-pends: {final}")
    print("ALL WEBHOOK ORDER CHECKS PASSED")

asyncio.run(main())

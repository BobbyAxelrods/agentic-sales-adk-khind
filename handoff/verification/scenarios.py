"""Scripted chats against `adk api_server` (real Gemini, no Chatwoot).

Start the server first, from the repo root:
    .venv/bin/adk api_server --port 8000 --session_service_uri memory:// .
Then: .venv/bin/python handoff/verification/scenarios.py [happy notcovered notworking friend linear switch legacy]
"""
import sys, time
import httpx
sys.path.insert(0, ".")
from google.adk.events import Event
from apps.services.replies import build_reply
from apps.prompts.khind_prompts import KHIND_PRODUCT_USPS, NOT_WORKING_HANDOFF_LINE

BASE, APP, USER = "http://127.0.0.1:8000", "apps", "verify"
only = set(sys.argv[1:])

def wait_ready():
    for _ in range(120):
        try:
            r = httpx.get(f"{BASE}/list-apps", timeout=2)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("server not ready")

print("apps:", wait_ready())
client = httpx.Client(timeout=180)
results = []

def new_session(state=None):
    r = client.post(f"{BASE}/apps/{APP}/users/{USER}/sessions", json={"state": state} if state else {})
    r.raise_for_status()
    return r.json()["id"]

def say(sid, text):
    r = client.post(f"{BASE}/run", json={"appName": APP, "userId": USER, "sessionId": sid,
                                        "newMessage": {"role": "user", "parts": [{"text": text}]}})
    r.raise_for_status()
    events = [Event.model_validate(e) for e in r.json()]
    reply = build_reply(events)
    tools = [c.name for e in events for c in e.get_function_calls()]
    state = client.get(f"{BASE}/apps/{APP}/users/{USER}/sessions/{sid}").json()["state"]
    print(f"\n>>> {text}\n[tools: {tools}] [stage: {state.get('purchase_stage')}] [product: {state.get('product_interest')}]"
          f" [escalated: {state.get('escalated')}/{state.get('escalation_label')}]\n{reply}")
    return reply, tools, state

def check(name, cond):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name)

USP = KHIND_PRODUCT_USPS
LOCQ = "Poskod & Kawasan"
ticks = lambda s: sum(1 for line in s.split(chr(10)) if line.strip().startswith("✅"))

def happy():
    print("\n===== Happy path =====")
    s = new_session()
    r, t, st = say(s, "hi")
    check("hi: list shown, still discovery", "ChillMaster" in r and st.get("purchase_stage", "discovery") == "discovery" and not st.get("product_interest"))
    r, t, st = say(s, "8")
    check("8: exact aircond USP once, no extra feature block", r.count(USP["aircond_kool_series"]) == 1 and ticks(r) == ticks(USP["aircond_kool_series"]))
    check("8: location question, stage location", LOCQ in r and st["purchase_stage"] == "location")
    r, t, st = say(s, "43000 Kajang")
    check("Kajang: covered line + kerja question", "liputan" in r and "bekerja" in r and "advance_purchase_stage" in t)
    check("Kajang: stage qualification, not escalated", st["purchase_stage"] == "qualification" and not st.get("escalated"))
    r, t, st = say(s, "ya saya kerja")
    check("kerja: RM1 line, no escalation", "RM1" in r and "tiada bayaran lain sekarang" in r and not st.get("escalated"))
    r, t, st = say(s, "ok")
    check("ok: BORANG sent once", r.count("BORANG PERMOHONAN KHIND") == 1 and st.get("application_form_sent") is True)
    r, t, st = say(s, "Nama saya Ali bin Abu, IC 000000-00-0000, email ali@example.com")
    check("fields: saved, no full form resent", "save_application_details" in t and "BORANG PERMOHONAN KHIND" not in r)
    check("fields: asks for a missing field", any(k in r for k in ("Whatsapp", "Alamat", "Pekerjaan", "Syarikat", "kecemasan", "Kecemasan")))

def not_covered():
    print("\n===== Not covered =====")
    s = new_session()
    r, t, st = say(s, "1")
    check("1: exact 592L USP + location question", r.count(USP["chillmaster_592l"]) == 1 and LOCQ in r)
    r, t, st = say(s, "Kapit, Sarawak")
    check("Kapit: escalated with coverage label", st.get("escalated") and st.get("escalation_label") == "coverage-unsupported-alternative")
    check("Kapit: one 'nanti' handoff line, no partner brand", r.count("nanti") == 1 and "rakan kongsi" not in r)

def not_working(first, area, answer, name):
    print(f"\n===== Not working: {name} =====")
    s = new_session()
    say(s, first)
    r, t, st = say(s, area)
    check(f"{name}: covered, stage qualification", st["purchase_stage"] == "qualification")
    r, t, st = say(s, answer)
    check(f"{name}: escalated with not-working", st.get("escalated") and st.get("escalation_label") == "not-working")
    check(f"{name}: exactly one handoff line", r.count("pemohon yang bekerja") == 1 and "RM1" not in r)

def linear():
    print("\n===== Linear rule =====")
    s = new_session()
    say(s, "4")
    r, t, st = say(s, "berapa harga?")
    check("price q: answered, location question repeated, stage unchanged", LOCQ in r and st["purchase_stage"] == "location" and "query_product_info" in t)
    check("price q: no USP resent", USP["washer_dryer_11_7"] not in r)

def switch():
    print("\n===== Product switch in qualification =====")
    s = new_session()
    say(s, "8")
    say(s, "Kajang, Selangor")
    r, t, st = say(s, "eh sebenarnya saya nak peti ais 592")
    check("switch: exact 592L USP once, no extra feature block", r.count(USP["chillmaster_592l"]) == 1 and ticks(r) == ticks(USP["chillmaster_592l"]))
    check("switch: kerja question repeated, stage qualification", "bekerja" in r and st["purchase_stage"] == "qualification" and st["product_interest"] == "chillmaster_592l")

def legacy():
    print("\n===== Legacy session at stage 'product' =====")
    s = new_session({"purchase_stage": "product", "product_interest": "aircond_kool_series", "pitched_products": ["aircond_kool_series"]})
    r, t, st = say(s, "Kajang, Selangor")
    check("legacy: ends in qualification with covered line", st["purchase_stage"] == "qualification" and "liputan" in r and "bekerja" in r)

SCEN = {
    "happy": happy,
    "notcovered": not_covered,
    "notworking": lambda: not_working("2", "Shah Alam", "tak kerja", "tak kerja"),
    "friend": lambda: not_working("3", "Petaling Jaya", "saya tak kerja, kawan saya yang kerja nak ambil", "friend works"),
    "linear": linear,
    "switch": switch,
    "legacy": legacy,
}
for key, fn in SCEN.items():
    if not only or key in only:
        try:
            fn()
        except Exception as exc:
            check(f"{key}: crashed ({exc!r})", False)

failed = [n for n, ok in results if not ok]
print(f"\n==== {len(results) - len(failed)}/{len(results)} checks passed ====")
for n in failed:
    print("FAILED:", n)

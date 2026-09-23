"""Scripted chats against `adk api_server` (real Gemini, no Chatwoot).

Start the server first, from the repo root (port 8001 leaves ADK Web on 8000 alone):
    .venv/bin/adk api_server --port 8001 --session_service_uri memory:// .
Then: KHIND_API_BASE=http://127.0.0.1:8001 .venv/bin/python handoff/verification/scenarios.py [names...]
Names: happy notcovered notworking friend linear switch legacy
       price592 postcode_only product_area mention menu_pending kb_gap switch_back completion
"""
import os, re, sys, time
import httpx
sys.path.insert(0, ".")
from google.adk.events import Event
from apps.services.replies import build_reply
from apps.prompts.khind_prompts import (
    APPLICATION_COMPLETE_LINE, KHIND_PRODUCT_USPS, NOT_WORKING_HANDOFF_LINE, PRODUCT_MENU,
)

BASE = os.environ.get("KHIND_API_BASE", "http://127.0.0.1:8000")
APP, USER = "apps", "verify"
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
GAP = "Pegawai kami akan sahkan"  # from KB_GAP_LINE
ticks = lambda s: sum(1 for line in s.split(chr(10)) if line.strip().startswith("✅"))
# True if the reply ends with a question, ignoring trailing emoji.
ends_with_question = lambda s: re.sub(r"[\s\U0001F000-\U0001FAFF☀-➿️]+$", "", s).endswith("?")

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

# --- Smoke-test failures of 2026-09-24, one scenario each ---

def usp_then_question_only(r, key):
    """After a first pick: the exact USP, then the question, with no model comment between."""
    return r.count(USP[key]) == 1 and r.split(USP[key])[-1].strip().startswith("Boleh kongsikan Poskod")

def price592():
    print("\n===== A3: 592L price =====")
    s = new_session()
    r, t, st = say(s, "1")
    check("A2: USP then the location question, no model comment", usp_then_question_only(r, "chillmaster_592l"))
    r, t, st = say(s, "Berapa harga ansuran bulanan untuk model ni?")
    check("A3: no Lite 480L prices (RM75/RM95)", "RM75" not in r and "RM95" not in r)
    check("A3: 592L prices from its own document (RM99/RM119)", "RM99" in r or "RM119" in r)
    check("A3: location question again, stage location, no handoff",
          LOCQ in r and st["purchase_stage"] == "location" and not st.get("escalated"))

def postcode_only():
    print("\n===== B10: postcode without a town =====")
    s = new_session()
    say(s, "1")
    r, t, st = say(s, "Poskod 96800")
    check("B10: no verdict, asks for the town, stage location",
          "ada dalam liputan" not in r and "belum ada liputan" not in r and "bandar" in r.lower()
          and st["purchase_stage"] == "location" and not st.get("escalated"))
    r, t, st = say(s, "Kapit")
    check("B10: then 'Kapit' -> not-covered handoff",
          st.get("escalation_label") == "coverage-unsupported-alternative" and "Kapit" in r and r.count("nanti") == 1)

def product_area():
    print("\n===== B11: product and area in one message =====")
    s = new_session()
    r, t, st = say(s, "Saya nak aircond, saya duduk Kajang Selangor")
    check("B11: exact aircond USP once", r.count(USP["aircond_kool_series"]) == 1 and ticks(r) == ticks(USP["aircond_kool_series"]))
    check("B11: covered line + kerja question, no location question",
          "ada dalam liputan" in r and "bekerja" in r and "Boleh kongsikan Poskod" not in r)
    check("B11: stage qualification, not escalated", st["purchase_stage"] == "qualification" and not st.get("escalated"))

def mention():
    print("\n===== C2: product named in a question =====")
    s = new_session()
    r, t, st = say(s, "Ada aircond tak?")
    check("C2: aircond picked", "set_product_interest" in t and st.get("product_interest") == "aircond_kool_series")
    check("C2: exact aircond USP once + location question", r.count(USP["aircond_kool_series"]) == 1 and LOCQ in r)

def menu_pending():
    print("\n===== D4-D6: list, repeat question, item outside the list =====")
    s = new_session()
    r, t, st = say(s, "7")
    check("7: USP then the location question, no model comment", usp_then_question_only(r, "drymaster_9kg"))
    r, t, st = say(s, "Ada produk apa lagi?")
    check("D4: grouped list copied exactly", PRODUCT_MENU in r)
    check("D4: location question (pending step), stage unchanged", LOCQ in r and st["purchase_stage"] == "location")
    r, t, st = say(s, "Waranti berapa tahun untuk produk ni?")
    check("D5: location question again, not 'which product'", LOCQ in r and "yang mana" not in r.lower())
    r, t, st = say(s, "KHIND ada jual TV atau microwave tak?")
    unseen_list = any(p in r for p in ("senarai tadi", "senarai produk tadi", "sebelum ini", "di atas"))
    check("D6: no brand-wide claim, no reference to an unseen list",
          "tidak menjual" not in r and (not unseen_list or PRODUCT_MENU in r))
    check("D6: location question again", LOCQ in r)

def kb_gap():
    print("\n===== E1: fact missing from the documents =====")
    s = new_session()
    r, t, st = say(s, "What is the monthly price for the air conditioner?")
    check("E1: no handoff", not st.get("escalated") and "escalate_to_live_agent" not in t)
    check("E1: gap line (the aircond document has no monthly price)", GAP in r)
    check("E1: aircond picked, location question", st.get("product_interest") == "aircond_kool_series" and LOCQ in r)

def switch_back():
    print("\n===== G6: back to an earlier product, with a question =====")
    s = new_session()
    say(s, "1")
    say(s, "Poskod 43000, Kajang Selangor")
    say(s, "Sebenarnya saya lebih berminat dengan mesin basuh front load")
    r, t, st = say(s, "Ok balik pada peti ais 592L tadi, berapa berat dia?")
    flat = r.replace(" ", "").lower()
    check("G6: active product back to 592L", st.get("product_interest") == "chillmaster_592l")
    check("G6: 85 kg from the 592L document, no Lite 480L figures", "85kg" in flat and "80kg" not in flat and "87kg" not in flat)
    check("G6: no handoff, kerja question, no USP repeat",
          not st.get("escalated") and "bekerja" in r and USP["chillmaster_592l"] not in r)

def completion():
    print("\n===== E4 / A10 / A11: after the form is complete =====")
    s = new_session()
    for text in ("1", "Poskod 43000, Kajang Selangor", "Ya saya kerja swasta", "Ok jom semak"):
        say(s, text)
    r, t, st = say(s, "Nama Ali bin Abu, No IC 900101015511, WhatsApp 0123456789, emel ali@example.com, "
                      "alamat No 5 Jalan Bunga Kajang, teknisi di ABC Sdn Bhd mula Jan 2020. "
                      "Kecemasan: Siti binti Ahmad, 0198887777, isteri")
    check("A10: complete, fixed completion line, ends with a question",
          st.get("application_complete") and APPLICATION_COMPLETE_LINE in r and ends_with_question(r))
    check("A10: no personal value echoed", "Ali" not in r and "900101015511" not in r)
    r, t, st = say(s, "Boleh hantar borang sekali lagi?")
    check("A11: no second form, ends with a question", "BORANG PERMOHONAN KHIND" not in r and ends_with_question(r))

SCEN = {
    "happy": happy,
    "notcovered": not_covered,
    "notworking": lambda: not_working("2", "Shah Alam", "tak kerja", "tak kerja"),
    "friend": lambda: not_working("3", "Petaling Jaya", "saya tak kerja, kawan saya yang kerja nak ambil", "friend works"),
    "linear": linear,
    "switch": switch,
    "legacy": legacy,
    "price592": price592,
    "postcode_only": postcode_only,
    "product_area": product_area,
    "mention": mention,
    "menu_pending": menu_pending,
    "kb_gap": kb_gap,
    "switch_back": switch_back,
    "completion": completion,
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

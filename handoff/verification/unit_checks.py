"""Offline checks for session tools, coverage, retrieval scoping, assembler, reply callbacks
and reply builder.

Run from the repo root: .venv/bin/python handoff/verification/unit_checks.py
"""
import asyncio
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, ".")
from google.adk.events import Event
from google.adk.models import LlmResponse
from google.adk.sessions.state import State
from google.genai import types as T

import apps.tools.escalation_tool as escalation_tool
import apps.tools.rag_tool as rag_tool
from apps.prompts.khind_assembler import get_khind_instruction, pending_step
from apps.prompts.khind_prompts import (
    APPLICATION_COMPLETE_LINE, CLOSING_FRAGMENT_RAW, COVERAGE_FRAGMENT_RAW,
    DISCOVERY_FRAGMENT_RAW, HANDOFF_FALLBACK_LINES, IC_PHOTO_QUESTION, KB_GAP_LINE,
    KHIND_CORE_RAW, KHIND_ESCALATION_RAW, KHIND_PRODUCT_USPS, LOCATION_QUESTION, PRODUCT_MENU,
)
from apps.services.coverage import check_coverage
from apps.services.replies import build_reply, drop_text_beside_coverage_call, insert_pending_usp
from apps.tools.escalation_tool import ESCALATION_LABELS
from apps.tools.session_tools import advance_purchase_stage, find_product_keys, set_product_interest

INV = "inv-1"  # invocation id of the fake turn
ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)

ctx = lambda **s: SimpleNamespace(invocation_id=INV, state=dict(s))

# --- set_product_interest ---
c = ctx(purchase_stage="discovery", pitched_products=[])
r = set_product_interest("8", c)
check(c.state["purchase_stage"] == "location", "first pick from discovery -> location")
check(r["purchase_stage"] == "location" and r["first_time"] and r["usp_sent_automatically"], "result has stage + usp flag")
check("usp" not in r and not any(KHIND_PRODUCT_USPS["aircond_kool_series"] in str(v) for v in r.values()), "result carries no USP text")
check(c.state["pending_usp_products"] == ["aircond_kool_series"], "first pick queues USP")

c = ctx(purchase_stage="product", product_interest="chillmaster_592l", pitched_products=["chillmaster_592l"])
r = set_product_interest("chillmaster_592l", c)
check(c.state["purchase_stage"] == "location" and not r["first_time"], "legacy 'product' stage -> location, not first time")
check("pending_usp_products" not in c.state, "repeat pick queues nothing")

c = ctx(purchase_stage="qualification", product_interest="aircond_kool_series", pitched_products=["aircond_kool_series"])
r = set_product_interest("peti ais 592".replace("peti ais ", ""), c)
check(c.state["purchase_stage"] == "qualification" and r["first_time"], "switch in qualification keeps stage")
check(c.state["pending_usp_products"] == ["chillmaster_592l"], "switch queues the new USP")
r2 = set_product_interest("chillmaster_592l", c)
check(not r2["first_time"] and c.state["pending_usp_products"] == ["chillmaster_592l"], "same product again adds nothing")

check(set_product_interest("front_load_washer_9kg", ctx())["status"] == "error", "bad key still errors")

# B11: at the location step the first-pick rule checks a place in the same message.
r = set_product_interest("aircond", ctx(purchase_stage="discovery"))
check("advance_purchase_stage" in r["reply_rule"] and "no" in r["reply_rule"].lower() and "description" in r["reply_rule"],
      "first pick at location: reply_rule checks a given place, still no description")
r = set_product_interest("front load", ctx(purchase_stage="qualification", product_interest="chillmaster_592l", pitched_products=["chillmaster_592l"]))
check("advance_purchase_stage" not in r["reply_rule"] and "pending step" in r["reply_rule"], "switch later: reply_rule asks the pending question only")

# --- find_product_keys (retrieval scope) ---
for text, want in {
    "berat peti ais ChillMaster 592L": ["chillmaster_592l"],
    "ansuran bulanan untuk ChillMaster 592L": ["chillmaster_592l"],
    "Harga bulanan untuk penyaman udara KOOL Series Inverter Aircond": ["aircond_kool_series"],
    "Waranti untuk DryMaster 9KG": ["drymaster_9kg"],
    "2-in-1 Washer Dryer 11KG/7KG harga": ["washer_dryer_11_7"],
    "beza ChillMaster Lite 480L dan ChillMaster X 466L": ["chillmaster_lite_480l", "chillmaster_x_466l"],
    "EcoWash Top Load 15KG": ["ecowash_top_15kg"],
    "harga RM 480 sebulan": [],
    "peti ais yang besar": [],
}.items():
    check(find_product_keys(text) == want, f"find_product_keys({text!r}) -> {want}")

# --- coverage verdicts (B rows and edge cases) ---
for (pc, town, st), want in {
    ("96800", "Kapit", "Sarawak"): "not_covered",      # B2
    ("93350", "Kuching", "Sarawak"): "covered",        # B3
    ("88000", "Kota Kinabalu", "Sabah"): "covered",    # B4
    ("", "Nabawan", "Sabah"): "not_covered",           # B5
    ("87000", "Labuan", ""): "not_covered",            # B6
    ("", "", "Singapore"): "not_covered",              # B7
    ("", "Singapore", ""): "not_covered",
    ("10450", "Georgetown", "Pulau Pinang"): "covered", # B8
    ("", "", "Sabah"): "need_town",                    # B9
    ("96800", "", ""): "need_town",                    # B10
    ("", "Kajang", "Selangor"): "covered",             # B11
    ("", "Kapit, Sarawak", ""): "not_covered",         # B12
    ("", "", "Penang"): "covered",
    ("", "", "N9"): "covered",
    ("", "", "Selangor Darul Ehsan"): "covered",
    ("", "Shah Alam", ""): "need_state",
    ("", "Likas, Kota Kinabalu", ""): "covered",
    ("", "Sibuti", "Sarawak"): "not_covered",
    ("", "KK", ""): "covered",
    ("", "Membakut (Town)", "Sabah"): "covered",
    ("", "", ""): "need_location",
}.items():
    check(check_coverage(pc, town, st).status == want, f"coverage({pc!r}, {town!r}, {st!r}) -> {want}")

# --- advance_purchase_stage (coverage decided in code) ---
check(advance_purchase_stage(ctx(purchase_stage="discovery"))["status"] == "error", "advance with no product errors")
for start in ("product", "location", "discovery"):
    c = ctx(purchase_stage=start, product_interest="aircond_kool_series")
    r = advance_purchase_stage(c, postcode="43000")
    check(c.state["purchase_stage"] == "qualification" and r["previous_stage"] == "location", f"covered from {start} -> qualification (previous_stage=location)")
c = ctx(purchase_stage="location", product_interest="chillmaster_592l")
r = advance_purchase_stage(c, town="Kajang", state="Selangor")
check(r["area"] == "Kajang, Selangor" and c.state["customer_location"] == "Kajang, Selangor", "covered: area returned, customer_location written")
c = ctx(purchase_stage="location", product_interest="chillmaster_592l")
r = advance_purchase_stage(c, postcode="96800")
check(r["status"] == "need_town" and "Sarawak" in r["ask"] and c.state["purchase_stage"] == "location"
      and "customer_location" not in c.state, "B10: postcode alone -> need_town, no verdict, stage kept")
r = advance_purchase_stage(c, town="Kapit")
check(r["status"] == "not_covered" and c.state["purchase_stage"] == "location"
      and c.state["customer_location"] == "96800 Kapit", "next turn 'Kapit' joins the saved 96800 -> not_covered")
c = ctx(purchase_stage="location", product_interest="chillmaster_592l")
r = advance_purchase_stage(c)
check(r["status"] == "need_location" and r["ask"] == LOCATION_QUESTION, "no place -> location question")
r = advance_purchase_stage(c, town="Shah Alam")
check(r["status"] == "need_state" and c.state["purchase_stage"] == "location", "town without state -> need_state")
c = ctx(purchase_stage="qualification", product_interest="chillmaster_592l")
r = advance_purchase_stage(c)
check(r["status"] == "ok" and c.state["purchase_stage"] == "qualification" and "ask" not in r, "later stage, no place -> no-op")
r = advance_purchase_stage(c, town="Kapit", state="Sarawak")
check(r["status"] == "not_covered" and c.state["purchase_stage"] == "qualification", "later stage, uncovered move -> not_covered, stage kept")

# --- assembler ---
inst = lambda **s: get_khind_instruction(SimpleNamespace(invocation_id=INV, state=s))
check(DISCOVERY_FRAGMENT_RAW in inst(purchase_stage="discovery"), "no product -> discovery")
check(DISCOVERY_FRAGMENT_RAW in inst(purchase_stage="location"), "no product, odd stage -> discovery")
for st in ("location", "product", "discovery"):
    i = inst(purchase_stage=st, product_interest="aircond_kool_series")
    check(COVERAGE_FRAGMENT_RAW in i and "Poskod & Kawasan" in i and CLOSING_FRAGMENT_RAW not in i, f"{st}+product -> coverage")
for st in ("qualification", "form"):
    i = inst(purchase_stage=st, product_interest="aircond_kool_series")
    check(CLOSING_FRAGMENT_RAW in i and "RM1" in i and "Baik, kawasan" in i and "slip gaji" not in i, f"{st} -> closing with RM1 + covered opener")
check("not-working" in KHIND_ESCALATION_RAW and "no-payslip" not in KHIND_ESCALATION_RAW, "escalation text uses not-working")
check("not-working" in ESCALATION_LABELS and "no-payslip-alternative" not in ESCALATION_LABELS, "tool labels updated")
check("Pendaftaran hanya RM1*, tiada bayaran lain sekarang. Jom semak kelayakan dulu?" in CLOSING_FRAGMENT_RAW, "approved RM1 sentence present")
check(HANDOFF_FALLBACK_LINES["not-working"] in CLOSING_FRAGMENT_RAW, "not-working line interpolated")
check(APPLICATION_COMPLETE_LINE in CLOSING_FRAGMENT_RAW and APPLICATION_COMPLETE_LINE.endswith("?"), "E4: completion line fixed, ends with a question")
check(KB_GAP_LINE in KHIND_CORE_RAW and "BUKAN serahan" in KHIND_CORE_RAW, "missing-fact line in core, marked as not a handoff")
check('only when query_product_info returns status "error"' in KHIND_ESCALATION_RAW, "rag-error only for a failed retrieval")
check("Kapit" not in COVERAGE_FRAGMENT_RAW and "advance_purchase_stage(postcode=" in COVERAGE_FRAGMENT_RAW, "coverage lists left the prompt; tool decides")

# D4/D5: the grouped list and the pending step are in every stage's instruction.
for s in ({}, {"product_interest": "drymaster_9kg", "purchase_stage": "location"},
          {"product_interest": "drymaster_9kg", "purchase_stage": "qualification"}):
    i = get_khind_instruction(SimpleNamespace(invocation_id=INV, state=s))
    check(PRODUCT_MENU in i and "- Pending step: " in i, f"menu + pending step in instruction for {s or 'new session'}")
for s, want in (
    ({"escalated": True, "product_interest": "x", "purchase_stage": "location"}, "handed to an officer"),
    ({}, "Choose a product"),
    ({"product_interest": "x", "purchase_stage": "location"}, LOCATION_QUESTION),
    ({"product_interest": "x", "purchase_stage": "product"}, LOCATION_QUESTION),
    ({"product_interest": "x", "purchase_stage": "qualification"}, "bekerja sekarang?"),
    ({"product_interest": "x", "purchase_stage": "qualification", "application_form_sent": True}, "missing_fields"),
    ({"product_interest": "x", "purchase_stage": "qualification", "application_form_sent": True, "application_complete": True}, IC_PHOTO_QUESTION),
):
    check(want in pending_step(s), f"pending step for {s} names {want[:30]!r}")

# --- insert_pending_usp ---
USP = KHIND_PRODUCT_USPS["aircond_kool_series"]
Q = "Boleh kongsikan Poskod & Kawasan pemasangan untuk saya semak liputan penghantaran percuma? 😊"
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))
out = insert_pending_usp(cb, resp)
check(out is not None and out.content.parts[0].text == f"{USP}\n\n{Q}", "callback prepends exact USP")
check(cb.state["pending_usp_products"] == [], "callback clears pending")

cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series"]})
fc = LlmResponse(content=T.Content(role="model", parts=[T.Part(function_call=T.FunctionCall(name="advance_purchase_stage", args={}))]))
check(insert_pending_usp(cb, fc) is None and cb.state["pending_usp_products"] == ["aircond_kool_series"], "function-call response untouched, pending kept")

cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series"]})
dup = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=f"{USP}\n\n{Q}")]))
insert_pending_usp(cb, dup)
check(dup.content.parts[0].text.count(USP) == 1, "no duplicate when USP already verbatim")

cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series"]})
empty = LlmResponse(content=None)
out = insert_pending_usp(cb, empty)
check(out.content.parts[0].text == USP, "empty response gets the USP")

cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series", "chillmaster_592l"]})
two = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))
insert_pending_usp(cb, two)
t = two.content.parts[0].text
check(t.index(USP) < t.index(KHIND_PRODUCT_USPS["chillmaster_592l"]) < t.index(Q), "two USPs in pick order, then question")

cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["aircond_kool_series"]})
check(insert_pending_usp(cb, LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]), partial=True)) is None, "partial response untouched")
check(insert_pending_usp(SimpleNamespace(invocation_id=INV, state={}), LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))) is None, "nothing pending -> untouched")

# B12: a handoff turn gets no USP, so an empty reply still gets the fixed handoff line.
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"], "escalated": True})
check(insert_pending_usp(cb, LlmResponse(content=None)) is None and cb.state["pending_usp_products"] == [], "escalated turn: USP dropped, pending cleared")

# --- text written beside a coverage call is dropped ---
early = LlmResponse(content=T.Content(role="model", parts=[
    T.Part(text="Baik, kawasan 96800 ada dalam liputan!"),
    T.Part(text="plan", thought=True),
    T.Part(function_call=T.FunctionCall(name="advance_purchase_stage", args={"postcode": "96800"}))]))
out = drop_text_beside_coverage_call(SimpleNamespace(invocation_id=INV, state={}), early)
check(out is not None and [bool(p.function_call) for p in out.content.parts] == [False, True]
      and out.content.parts[0].thought, "text beside advance_purchase_stage dropped; thought and call kept")
handoff = LlmResponse(content=T.Content(role="model", parts=[
    T.Part(text="Maaf sangat cik/tuan, kawasan Kapit belum ada liputan."),
    T.Part(function_call=T.FunctionCall(name="escalate_to_live_agent", args={"label": "coverage-unsupported-alternative"}))]))
check(drop_text_beside_coverage_call(SimpleNamespace(invocation_id=INV, state={}), handoff) is None, "handoff line beside escalate call kept")
check(drop_text_beside_coverage_call(SimpleNamespace(invocation_id=INV, state={}), LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))) is None, "plain text untouched")

# --- query_product_info: search limited to the named or active product ---
calls, listing = [], []
stamp = lambda hour: datetime(2026, 9, 12, hour, tzinfo=timezone.utc)
FILES = [SimpleNamespace(name=f"c/ragFiles/{fid}", display_name=dn, create_time=t) for fid, dn, t in (
    ("old-dhp90", rag_tool.PRODUCT_DOCUMENTS["drymaster_9kg"], stamp(3)),
    ("new-dhp90", rag_tool.PRODUCT_DOCUMENTS["drymaster_9kg"], stamp(4)),
    ("id-592", rag_tool.PRODUCT_DOCUMENTS["chillmaster_592l"], stamp(4)),
)]
def fake_list_files(corpus_name):
    listing.append(corpus_name)
    return iter(FILES)
def fake_retrieval_query(text, rag_resources, rag_retrieval_config):
    calls.append((rag_resources[0].rag_file_ids, rag_retrieval_config.top_k))
    chunk = SimpleNamespace(text=f"chunk for {text}", source_display_name="src")
    return SimpleNamespace(contexts=SimpleNamespace(contexts=[chunk]))
rag_tool.vrag = SimpleNamespace(list_files=fake_list_files, retrieval_query=fake_retrieval_query)
rag_tool._file_ids = None
run = lambda q, **s: asyncio.run(rag_tool.query_product_info(q, SimpleNamespace(invocation_id=INV, state=s)))

r = run("berat peti ais ChillMaster 592L", product_interest="front_load_9kg")
check(calls[-1] == (["id-592"], 8) and r["scope"] == "product" and r["products"] == ["chillmaster_592l"],
      "G6: product named in the query wins over a stale active product; whole document (top_k 8)")
r = run("waranti", product_interest="drymaster_9kg")
check(calls[-1][0] == ["new-dhp90"], "active product used when the query names none; newest duplicate chosen")
check(len(listing) == 1, "file ids listed once per process")
r = run("ada promosi apa?")
check(calls[-1] == (None, 3) and r["scope"] == "corpus", "no product at all -> whole corpus, top_k 3")
state = {"product_interest": "chillmaster_592l"}
ctx_rag = SimpleNamespace(invocation_id=INV, state=state)
asyncio.run(rag_tool.query_product_info("harga", ctx_rag))
check(any(k.startswith("rag_0_chillmaster_592l_") for k in state), "cache key names the product scope")
check(state.get("reply_facts_invocation") == INV, "query_product_info marks the turn")
def failing_retrieval(**kwargs):
    raise RuntimeError("vertex down")
rag_tool.vrag = SimpleNamespace(list_files=fake_list_files, retrieval_query=failing_retrieval)
state = {"product_interest": "chillmaster_592l"}
r = asyncio.run(rag_tool.query_product_info("dimensi", SimpleNamespace(invocation_id=INV, state=state)))
check(r["status"] == "error" and r.get("rag_error") and not any(k.startswith("rag_") for k in state), "retrieval error -> status error, not cached")
listed_before = len(listing)
rag_tool.vrag = SimpleNamespace(list_files=fake_list_files, retrieval_query=lambda **kw: SimpleNamespace(contexts=SimpleNamespace(contexts=[])))
r = run("berat 592L", product_interest="chillmaster_592l")
check(len(listing) == listed_before + 1 and r["status"] == "ok" and r["results"] == [], "zero hits -> file ids reloaded once, then ok/empty")

# --- escalation with a real ADK State (dict(state) used to raise KeyError 0) ---
seen = {}
async def fake_escalate(conversation_id, label, state):
    seen.update(state)
    return True
escalation_tool.chatwoot = SimpleNamespace(escalate_conversation=fake_escalate)
adk_state = State({"chatwoot_conversation_id": "42", "customer_location": "96800 Kapit"}, {})
r = asyncio.run(escalation_tool.escalate_to_live_agent("coverage-unsupported-alternative", SimpleNamespace(invocation_id=INV, state=adk_state)))
check(r["status"] == "ok" and seen.get("customer_location") == "96800 Kapit", "escalation passes the full state (incl. customer_location) to Chatwoot")


# --- model-written USP copy is replaced by the exact USP ---
U592 = KHIND_PRODUCT_USPS["chillmaster_592l"]
KQ = "Boleh saya tahu cik/tuan bekerja sekarang?"
for label, model_text in {
    "blank line before question": "*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar 592L - ruang luas.\n✅ Teknologi Inverter.\n\n" + KQ,
    "no blank line before question": "*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar 592L.\n" + KQ,
}.items():
    cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"]})
    resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=model_text)]))
    insert_pending_usp(cb, resp)
    check(resp.content.parts[0].text == f"{U592}\n\n{KQ}", f"USP copy replaced ({label})")
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text="*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar.")]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == U592, "copy-only reply becomes exactly the USP")


# --- run-1 regression: uppercase title + invented bullets, and bold text that must stay ---
run1 = ("*KHIND CHILLMASTER 592L* ✨\n"
        "✅ Ruang simpanan yang luas - 592L kapasiti bersih, sesuai untuk keluarga besar.\n"
        "✅ Waranti 12 tahun untuk kompresor dan 2 tahun untuk alat ganti.\n\n" + KQ)
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=run1)]))
insert_pending_usp(cb, resp)
out = resp.content.parts[0].text
check(out == f"{U592}\n\n{KQ}" and "Waranti 12 tahun" not in out, "run-1 paraphrase (other title case, invented facts) removed")
keep = "Harga *RM3,500* untuk belian terus.\n*Pendaftaran hanya RM1*, tiada bayaran lain sekarang.\n" + KQ
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=keep)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{U592}\n\n{keep}", "ordinary bold text and question kept")

# --- a plain pick keeps only the model's closing question (its own praise or claims are dropped) ---
LQ = LOCATION_QUESTION
chatter = "Wah, pilihan yang bagus! *ChillMaster 592L (Side-by-Side)* memang pilihan popular.\n\n" + LQ
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=chatter)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{U592}\n\n{LQ}", "plain pick: model praise dropped, USP + question only")
claim = "DryMaster: *Penjimatan tenaga elektrik sehingga 50%*!\n\n" + LQ + "\n\nKami tunggu ya."
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["drymaster_9kg"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=claim)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{KHIND_PRODUCT_USPS['drymaster_9kg']}\n\n{LQ}", "plain pick: invented claim dropped; the question kept even when not last")
praise_in_question = "Baik, pilihan yang bagus! Untuk saya semak liputan, boleh kongsikan *Poskod & Kawasan*? 😊"
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_x_466l"], "purchase_stage": "location"})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=praise_in_question)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{KHIND_PRODUCT_USPS['chillmaster_x_466l']}\n\n{LQ}", "plain pick at the location step: exactly USP + the fixed location question")
switch_q = "Faham! Boleh saya tahu cik/tuan bekerja sekarang?"
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["front_load_9kg"], "purchase_stage": "qualification"})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text="Mesin ini memang terbaik!\n\n" + switch_q)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{KHIND_PRODUCT_USPS['front_load_9kg']}\n\n{switch_q}", "switch at a later step: the model's closing question kept")
answer = "Harga *RM99/bulan* (Super Saver) atau *RM119/bulan* (Smart Value) untuk 60 bulan.\n\n" + LQ
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"], "reply_facts_invocation": INV})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=answer)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{U592}\n\n{answer}", "pick + product answer in the same turn: answer kept")
cb = SimpleNamespace(invocation_id=INV, state={"pending_usp_products": ["chillmaster_592l"], "reply_facts_invocation": "older-turn"})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=answer)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{U592}\n\n{LQ}", "an answer marker from an older turn does not count")
c = ctx(purchase_stage="location", product_interest="chillmaster_592l")
advance_purchase_stage(c, postcode="43000")
check(c.state.get("reply_facts_invocation") == INV, "advance_purchase_stage marks the turn")

# --- build_reply ---
A = "khind_sales_agent"
def ev(parts, author=A, partial=None):
    return Event(author=author, invocation_id="i", content=T.Content(role="user" if author == "user" else "model", parts=parts), partial=partial)
call = lambda label: T.Part(function_call=T.FunctionCall(name="escalate_to_live_agent", args={"label": label}))
resp_part = T.Part(function_response=T.FunctionResponse(name="escalate_to_live_agent", response={"status": "ok"}))
NANTI = "Maaf sangat cik/tuan, kawasan Kapit belum ada liputan KHIND buat masa ini. 🙏 Pegawai kami akan hubungi cik/tuan nanti ya."

check(build_reply([ev([call("coverage-unsupported-alternative")]), ev([resp_part]), ev([T.Part(text=NANTI)])]) == NANTI, "call-only escalate, line after tool kept")
check(build_reply([ev([T.Part(text=NANTI), call("coverage-unsupported-alternative")]), ev([resp_part]), ev([T.Part(text="Baik, saya sudah sambungkan anda.")])]) == NANTI, "line with call kept, second line dropped")
check(build_reply([ev([call("not-working")]), ev([resp_part]), ev([T.Part(text="")])]) == HANDOFF_FALLBACK_LINES["not-working"], "silent handoff gets label fallback")
check(build_reply([ev([call("human-required")]), ev([resp_part])]).startswith("Baik, saya sambungkan"), "unknown label gets default line")
check(build_reply([ev([T.Part(text="hi")], author="user"), ev([T.Part(text="draft")], partial=True), ev([T.Part(text="thinking", thought=True), T.Part(text="Jawapan.")])]) == "Jawapan.", "user/partial/thought skipped")
check(build_reply([ev([T.Part(text="A")]), ev([T.Part(text="A")]), ev([T.Part(text="B")])]) == "A\n\nB", "exact repeats skipped, blank-line join")
check(build_reply([]) == "", "no events -> empty")
print(f"\nALL {ok} CHECKS PASSED")

"""Offline checks for session tools, assembler, USP callback and reply builder.

Run from the repo root: .venv/bin/python handoff/verification/unit_checks.py
"""
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")
from google.adk.events import Event
from google.adk.models import LlmResponse
from google.genai import types as T

from apps.prompts.khind_assembler import get_khind_instruction
from apps.prompts.khind_prompts import (
    CLOSING_FRAGMENT_RAW, COVERAGE_FRAGMENT_RAW, DISCOVERY_FRAGMENT_RAW,
    HANDOFF_FALLBACK_LINES, KHIND_ESCALATION_RAW, KHIND_PRODUCT_USPS,
)
from apps.services.replies import build_reply, insert_pending_usp
from apps.tools.escalation_tool import ESCALATION_LABELS
from apps.tools.session_tools import advance_purchase_stage, set_product_interest

ok = 0
def check(cond, msg):
    global ok
    assert cond, msg
    ok += 1
    print("PASS", msg)

ctx = lambda **s: SimpleNamespace(state=dict(s))

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

# --- advance_purchase_stage ---
check(advance_purchase_stage(ctx(purchase_stage="discovery"))["status"] == "error", "advance with no product errors")
for start in ("product", "location", "discovery"):
    c = ctx(purchase_stage=start, product_interest="aircond_kool_series")
    r = advance_purchase_stage(c)
    check(c.state["purchase_stage"] == "qualification" and r["previous_stage"] == "location", f"advance from {start} -> qualification (previous_stage=location)")

# --- assembler ---
inst = lambda **s: get_khind_instruction(SimpleNamespace(state=s))
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

# --- insert_pending_usp ---
USP = KHIND_PRODUCT_USPS["aircond_kool_series"]
Q = "Boleh kongsikan Poskod & Kawasan pemasangan untuk saya semak liputan penghantaran percuma? 😊"
cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))
out = insert_pending_usp(cb, resp)
check(out is not None and out.content.parts[0].text == f"{USP}\n\n{Q}", "callback prepends exact USP")
check(cb.state["pending_usp_products"] == [], "callback clears pending")

cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series"]})
fc = LlmResponse(content=T.Content(role="model", parts=[T.Part(function_call=T.FunctionCall(name="advance_purchase_stage", args={}))]))
check(insert_pending_usp(cb, fc) is None and cb.state["pending_usp_products"] == ["aircond_kool_series"], "function-call response untouched, pending kept")

cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series"]})
dup = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=f"{USP}\n\n{Q}")]))
insert_pending_usp(cb, dup)
check(dup.content.parts[0].text.count(USP) == 1, "no duplicate when USP already verbatim")

cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series"]})
empty = LlmResponse(content=None)
out = insert_pending_usp(cb, empty)
check(out.content.parts[0].text == USP, "empty response gets the USP")

cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series", "chillmaster_592l"]})
two = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))
insert_pending_usp(cb, two)
t = two.content.parts[0].text
check(t.index(USP) < t.index(KHIND_PRODUCT_USPS["chillmaster_592l"]) < t.index(Q), "two USPs in pick order, then question")

cb = SimpleNamespace(state={"pending_usp_products": ["aircond_kool_series"]})
check(insert_pending_usp(cb, LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]), partial=True)) is None, "partial response untouched")
check(insert_pending_usp(SimpleNamespace(state={}), LlmResponse(content=T.Content(role="model", parts=[T.Part(text=Q)]))) is None, "nothing pending -> untouched")


# --- model-written USP copy is replaced by the exact USP ---
U592 = KHIND_PRODUCT_USPS["chillmaster_592l"]
KQ = "Boleh saya tahu cik/tuan bekerja sekarang?"
for label, model_text in {
    "blank line before question": "*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar 592L - ruang luas.\n✅ Teknologi Inverter.\n\n" + KQ,
    "no blank line before question": "*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar 592L.\n" + KQ,
}.items():
    cb = SimpleNamespace(state={"pending_usp_products": ["chillmaster_592l"]})
    resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=model_text)]))
    insert_pending_usp(cb, resp)
    check(resp.content.parts[0].text == f"{U592}\n\n{KQ}", f"USP copy replaced ({label})")
cb = SimpleNamespace(state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text="*KHIND ChillMaster 592L* ✨\n✅ Kapasiti besar.")]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == U592, "copy-only reply becomes exactly the USP")


# --- run-1 regression: uppercase title + invented bullets, and bold text that must stay ---
run1 = ("*KHIND CHILLMASTER 592L* ✨\n"
        "✅ Ruang simpanan yang luas - 592L kapasiti bersih, sesuai untuk keluarga besar.\n"
        "✅ Waranti 12 tahun untuk kompresor dan 2 tahun untuk alat ganti.\n\n" + KQ)
cb = SimpleNamespace(state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=run1)]))
insert_pending_usp(cb, resp)
out = resp.content.parts[0].text
check(out == f"{U592}\n\n{KQ}" and "Waranti 12 tahun" not in out, "run-1 paraphrase (other title case, invented facts) removed")
keep = "Harga *RM3,500* untuk belian terus.\n*Pendaftaran hanya RM1*, tiada bayaran lain sekarang.\n" + KQ
cb = SimpleNamespace(state={"pending_usp_products": ["chillmaster_592l"]})
resp = LlmResponse(content=T.Content(role="model", parts=[T.Part(text=keep)]))
insert_pending_usp(cb, resp)
check(resp.content.parts[0].text == f"{U592}\n\n{keep}", "ordinary bold text and question kept")

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

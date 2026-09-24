"""Rule checks over an extract_run.py dump: fixed lines, USP placement, emoji, personal data.

Run from the repo root, after extract_run.py:
    .venv/bin/python handoff/verification/check_run.py <out_dir>/run.json

Lists, per turn:
- a first pick (set_product_interest, first_time): whether the reply starts with the exact
  approved USP and what follows it (LOCATION_QUESTION, KERJA_QUESTION, the covered line, or other
  text). With a handoff in the same turn, the USP must be absent (B12).
- advance_purchase_stage: not_covered replies against the fixed line with `area`, and whether
  escalate_to_live_agent was also called; covered replies against the covered line; need_* asks.
- handoff lines (the not-working line must be exact), the RM1 line, the form-complete line;
- personal values from application_details echoed in a reply (PDPA);
- "senarai" in a reply that does not show the product list (D6);
- replies with more than one "?", empty replies, and replies with no emoji (E4).
The covered, not-covered and RM1 lines are copied from the prompt fragments in khind_prompts.py.
"""

import json
import re
import sys

sys.path.insert(0, ".")

from apps.prompts.khind_prompts import (  # noqa: E402
    APPLICATION_COMPLETE_LINE,
    KERJA_QUESTION,
    KHIND_PRODUCT_USPS,
    LOCATION_QUESTION,
    NOT_WORKING_HANDOFF_LINE,
    PRODUCT_MENU,
)

EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅✨‼⁉⃣]")
NOT_COVERED = (
    "Maaf sangat cik/tuan, kawasan {} belum ada liputan KHIND buat masa ini. 🙏 "
    "Pegawai kami akan hubungi cik/tuan nanti ya."
)
COVERED = "Baik, kawasan {} ada dalam liputan penghantaran & pemasangan kami! 🚚✨"
RM1_LINE = "Terbaik! 👍 *Pendaftaran hanya RM1*, tiada bayaran lain sekarang. Jom semak kelayakan dulu?"

run = json.load(open(sys.argv[1]))
no_emoji = []
for session in run:
    sid = session["session_id"][:8]
    personal = [v for v in (session["final_state"].get("application_details") or {}).values() if v]
    for n, turn in enumerate(session["turns"], 1):
        reply = turn["reply"]
        tag = f"{sid} t{n} {turn['user'][:40]!r}"
        if not reply:
            print(f"EMPTY REPLY      {tag}")
            continue
        if not EMOJI.search(reply):
            no_emoji.append(tag)
        calls = [c["name"] for step in turn["steps"] for c in step["calls"]]
        resps = {r["name"]: r["response"] or {} for step in turn["steps"] for r in step["responses"]}
        pick, coverage = resps.get("set_product_interest"), resps.get("advance_purchase_stage")

        if pick and pick.get("first_time"):
            usp = KHIND_PRODUCT_USPS[pick["product_interest"]]
            if (coverage or {}).get("escalated"):
                print(f"FIRST PICK       {tag}: handoff turn, USP absent={usp not in reply}")
            elif not reply.startswith(usp):
                print(f"FIRST PICK       {tag}: USP NOT ON TOP")
            else:
                rest = reply[len(usp):].strip()
                if rest == LOCATION_QUESTION:
                    kind = "LOCATION_QUESTION"
                elif rest == KERJA_QUESTION:
                    kind = "KERJA_QUESTION"
                elif coverage and rest.startswith(COVERED.format(coverage.get("area"))):
                    kind = "covered line"
                else:
                    kind = f"other: {rest[:160]!r}"
                print(f"FIRST PICK       {tag}: USP + {kind}")
        if coverage:
            status = coverage.get("status")
            if status == "not_covered":
                print(f"NOT COVERED      {tag}: exact line={reply == NOT_COVERED.format(coverage['area'])} "
                      f"escalate call={'escalate_to_live_agent' in calls} label={coverage.get('label')}")
            elif status == "ok" and coverage.get("previous_stage") == "location":
                line = COVERED.format(coverage["area"])
                kerja = KERJA_QUESTION.split("?")[0] + "?"
                print(f"COVERED          {tag}: line present={line in reply} "
                      f"kerja question last={reply.rstrip(' 😊').endswith(kerja)}")
            elif status and status.startswith("need_"):
                print(f"{status.upper():<16} {tag}: ask={coverage.get('ask')!r} reply={reply!r}")
        if "escalate_to_live_agent" in calls:
            label = resps.get("escalate_to_live_agent", {}).get("label")
            detail = f"exact line={reply == NOT_WORKING_HANDOFF_LINE}" if label == "not-working" else repr(reply)
            print(f"HANDOFF          {tag}: {label} {detail}")
        if (resps.get("save_application_details") or {}).get("status") == "complete":
            print(f"FORM COMPLETE    {tag}: exact line={reply == APPLICATION_COMPLETE_LINE}")
        if "Pendaftaran hanya RM1" in reply:
            print(f"RM1              {tag}: exact={reply == RM1_LINE} starts with line={reply.startswith(RM1_LINE)}")
        echoed = [v for v in personal if v in reply]
        if echoed:
            print(f"PERSONAL ECHO    {tag}: {echoed}")
        if "senarai" in reply.lower() and PRODUCT_MENU not in reply:
            print(f"SENARAI, NO LIST {tag}: {reply[:160]!r}")
        if reply.count("?") > 1:
            print(f"{reply.count('?')} QUESTIONS      {tag}: {reply[-200:]!r}")

print("\nREPLIES WITH NO EMOJI:", no_emoji or "none")

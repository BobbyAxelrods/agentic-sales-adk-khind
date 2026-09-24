"""Audit checks over an extract_run.py dump: figures, text beside tool calls, silent handoffs.

Run from the repo root, after extract_run.py:
    .venv/bin/python handoff/verification/trace_run.py <out_dir>/run.json

- A turn with a query_product_info search: every number in the reply (approved USP blocks, the
  product list, the discovery question and "RM1" removed) must appear in the text of the chunks
  returned in the same turn. Numbers that do not are listed as missing. Check their meaning too:
  a number can appear in the chunks for another reason.
- A turn with no search: numbers in the reply are listed for a manual check (echoes, the form).
- Customer-visible text written in the same step as a tool call is listed (B6 in rerun 2).
- Handoff turns that ended with no text are listed.
"""

import json
import re
import sys

sys.path.insert(0, ".")

from apps.prompts.khind_prompts import (  # noqa: E402
    DISCOVERY_QUESTION,
    KHIND_PRODUCT_USPS,
    PRODUCT_MENU,
)

FIXED_TEXTS = [*KHIND_PRODUCT_USPS.values(), PRODUCT_MENU, DISCOVERY_QUESTION]
NUMBER = re.compile(r"\d[\d,.]*")

run = json.load(open(sys.argv[1]))
beside_calls, silent_handoffs = [], []
for session in run:
    sid = session["session_id"][:8]
    for turn in session["turns"]:
        user = turn["user"][:50]
        chunks = [
            chunk
            for step in turn["steps"]
            for resp in step["responses"]
            if resp["name"] == "query_product_info"
            for chunk in (resp["response"] or {}).get("results", [])
        ]
        for step in turn["steps"]:
            if step["text"] and step["calls"]:
                beside_calls.append((sid, user, [c["name"] for c in step["calls"]], step["text"][:120]))
        handed_over = any(
            (resp["response"] or {}).get("escalated")
            for step in turn["steps"]
            for resp in step["responses"]
        )
        if handed_over and not turn["steps"][-1]["text"]:
            silent_handoffs.append((sid, user))

        reply = turn["reply"]
        for text in FIXED_TEXTS:
            reply = reply.replace(text, "")
        reply = reply.replace("RM1", "")
        figures = [f.rstrip(".,") for f in NUMBER.findall(reply)]
        if not chunks:
            if figures:
                print(f"NO SEARCH {sid} {user!r}: figures {figures}")
            continue
        corpus = "\n".join(c.get("text", "") for c in chunks).replace(",", "")
        sources = sorted({c.get("source") for c in chunks})
        missing = [f for f in figures if f.replace(",", "") not in corpus]
        print(f"SEARCH    {sid} {user!r} sources={sources}\n          figures={figures} missing={missing}")

print("\nTEXT BESIDE TOOL CALLS:")
for item in beside_calls:
    print("  ", item)
print("HANDOFF TURNS WITH NO TEXT:", silent_handoffs)

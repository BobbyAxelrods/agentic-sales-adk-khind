"""Dump an ADK Web test run from apps/.adk/session.db (opened read-only) for auditing.

Run from the repo root:
    .venv/bin/python handoff/verification/extract_run.py 2026-09-23T20:05:00Z [out_dir]

Takes every session created at or after the given UTC time and writes to out_dir
(default: the current directory):
  transcripts.txt  one block per session, turn by turn: user text, tool calls, tool results
                   (RAG chunk sources + text), model text, and the build_reply() output that
                   WhatsApp would have received, then the final state.
  run.json         the same data, structured, with the full RAG chunk text (for tracing every
                   figure in a reply to the `source` of the chunks returned in that turn).
Map sessions to smoke-test rows by order and first message.
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from google.adk.events import Event  # noqa: E402

from apps.services.replies import build_reply  # noqa: E402

DB = "file:apps/.adk/session.db?mode=ro"
start = datetime.fromisoformat(sys.argv[1].replace("Z", "+00:00")).astimezone(timezone.utc).timestamp()
out = Path(sys.argv[2] if len(sys.argv) > 2 else ".")


def ts(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%H:%M:%SZ")


con = sqlite3.connect(DB, uri=True)
sessions = con.execute(
    "select id, state, create_time from sessions where create_time >= ? order by create_time", (start,)
).fetchall()

run, lines = [], []
for sid, state, ctime in sessions:
    rows = con.execute(
        "select invocation_id, timestamp, event_data from events where session_id=? order by timestamp", (sid,)
    ).fetchall()
    turns: list[dict] = []
    for inv, t, data in rows:
        if not turns or turns[-1]["inv"] != inv:
            turns.append({"inv": inv, "t": t, "events": []})
        turns[-1]["events"].append(Event.model_validate_json(data))

    record = {"session_id": sid, "created": ts(ctime), "final_state": json.loads(state), "turns": []}
    lines += ["=" * 100, f"SESSION {sid}  created {ts(ctime)}  turns={len(turns)}"]
    for turn in turns:
        t_rec = {"t": ts(turn["t"]), "user": "", "steps": [], "reply": ""}
        agent_events = []
        for ev in turn["events"]:
            parts = ev.content.parts if ev.content else []
            if ev.author == "user":
                t_rec["user"] += "".join(p.text or "" for p in parts)
                continue
            agent_events.append(ev)
            step = {"calls": [], "responses": [], "text": ""}
            for p in parts or []:
                if p.function_call:
                    step["calls"].append({"name": p.function_call.name, "args": p.function_call.args})
                elif p.function_response:
                    step["responses"].append({"name": p.function_response.name, "response": p.function_response.response})
                elif p.text and not p.thought:
                    step["text"] += p.text
            t_rec["steps"].append(step)
        t_rec["reply"] = build_reply(agent_events)
        record["turns"].append(t_rec)

        lines += ["-" * 100, f"[{t_rec['t']}] USER: {t_rec['user']}"]
        for step in t_rec["steps"]:
            for c in step["calls"]:
                lines.append(f"   CALL {c['name']}({json.dumps(c['args'], ensure_ascii=False)})")
            for r in step["responses"]:
                resp = r["response"] or {}
                if r["name"] == "query_product_info":
                    lines.append(f"   RESP query_product_info status={resp.get('status')} scope={resp.get('scope')} "
                                 f"products={resp.get('products')}")
                    for chunk in resp.get("results", []):
                        lines.append(f"      src={chunk.get('source')}  | {chunk.get('text', '')[:300]!r}")
                else:
                    lines.append(f"   RESP {r['name']} {json.dumps(resp, ensure_ascii=False)[:400]}")
            if step["text"]:
                lines.append(f"   TEXT({'with-call' if step['calls'] else 'plain'}): {step['text']!r}")
        lines.append(f"   >>> WHATSAPP: {t_rec['reply']!r}")
    final = {k: v for k, v in record["final_state"].items() if not k.startswith("rag_")}
    lines.append("FINAL STATE: " + json.dumps(final, ensure_ascii=False)[:800])
    run.append(record)

out.mkdir(parents=True, exist_ok=True)
(out / "run.json").write_text(json.dumps(run, ensure_ascii=False, indent=1, default=str))
(out / "transcripts.txt").write_text("\n".join(lines))
print(f"{len(sessions)} sessions, {sum(len(s['turns']) for s in run)} turns -> {out}")

# KHIND Sales Agent — Code Review Tracker

> Last updated: 2026-09-12 · Round 11
> Status: **All bugs resolved. 3 items pending (2 data, 1 verify).**

---

## Architecture

```
WhatsApp Customer
      │
      ▼
Chatwoot  ← Agent Bot integration
           Only fires webhook for INCOMING customer messages.
      │
      ▼
POST /webhook  (apps/webhook.py)
      │
      ├─ extract session_id         → discard if empty
      ├─ store chatwoot_conversation_id in session state
      │
      ├── Route A: list reply
      │     resolve_product_selection()
      │     run_turn("[PRODUCT_SELECTED:key]")
      │     send_text → set_conversation_pending → _deliver_media
      │
      └── Route B: text message
            _maybe_send_catalog()   ← before run_turn
            run_turn(message_text)
            send_text → set_conversation_pending (skip if escalated)
            _deliver_media
            _maybe_escalate()       ← safety net only
      │
      ▼
apps/runner.py  run_turn()
      Bootstrap: load Vertex once → InMemory cache (zero latency hot path)
      After turn: asyncio.create_task(_flush_to_vertex)  ← non-blocking
      │
      ▼
apps/agent.py  root_agent (LlmAgent, gemini-2.5-flash, temp=0.3, max_tokens=250)
      │
      ├─ set_product_interest()        session_tools.py
      ├─ advance_purchase_stage()      session_tools.py
      ├─ mark_application_form_sent()  session_tools.py
      ├─ save_application_details()    session_tools.py
      ├─ query_product_info()          rag_tool.py → Vertex AI RAG
      └─ escalate_to_live_agent()      escalation_tool.py
                │ async — calls Chatwoot directly during LLM turn
                ▼
         chatwoot.escalate_conversation()
         1. toggle status → "open"  (disables bot gate)
         2. parallel: label + private note + assign agent 180662
```

---

## Session State

| Variable | Set by | Used by | Purpose |
|---|---|---|---|
| `purchase_stage` | `set_product_interest`, `advance_purchase_stage` | assembler | Which prompt fragment to inject |
| `product_interest` | `set_product_interest` | assembler, `_deliver_media` | Active product key |
| `pitched_products` | `set_product_interest` | assembler | USP shown once only per product |
| `rag_cache_generation` | `set_product_interest` | `query_product_info` | Bust cache on product switch |
| `rag_{gen}_{hash}` | `query_product_info` | `query_product_info` | Per-session RAG cache |
| `escalated` | `escalate_to_live_agent` | webhook | Skip bot gate, skip `_maybe_escalate` retry |
| `escalation_label` | `escalate_to_live_agent` | `_maybe_escalate` | Chatwoot label |
| `chatwoot_conversation_id` | webhook before turn | `escalation_tool` | Tool calls Chatwoot directly |
| `application_form_sent` | `mark_application_form_sent` | same | Send form once only |
| `application_details` | `save_application_details` | same | PII — never echoed in reply |
| `application_complete` | `save_application_details` | — | All 11 fields collected |
| `initial_media_sent_products` | `get_initial_media_plan` | same | Deliver media once per product |
| `catalog_sent` | `patch_session_state` | `_maybe_send_catalog` | Send menu once per session |

### Stage Flow
```
discovery → product → location → qualification → form (terminal)
            ↑
  set_product_interest()  advance_purchase_stage() ×3
```

### Assembler Fragment per Stage

| Condition | Fragment |
|---|---|
| `discovery`, no product | DISCOVERY |
| product set, not yet pitched | PRODUCT_USP |
| product set, already pitched | PRODUCT_RAG |
| `location` | COVERAGE |
| `qualification` or `form` | CLOSING |

---

## File Review

### `apps/config.py` ✅
All env vars correct. `.env` fully populated.

| Key | Value |
|---|---|
| `RAG_CORPUS_NAME` | `ragCorpora/2305843009213693952` |
| `GCS_BUCKET` | `khind_2028` |
| `CHATWOOT_HUMAN_AGENT_ID` | `180662` |
| `PORT` | `8081` |

---

### `apps/main.py` ✅
Lifespan pre-warms runner. Logging configured after uvicorn handlers. `/health` endpoint. `reload=False`.

---

### `apps/agent.py` ✅
- `escalate_to_live_agent` is `async def` — ADK supports async tools natively
- `instruction=get_khind_instruction` — callable, ADK calls it each turn with context
- `temperature=0.3`, `max_output_tokens=250`
- **Watch:** raise `max_output_tokens` to 400 if closing form gets cut off in production

---

### `apps/webhook.py` ✅
- `_is_outgoing` removed (Round 10) — Agent Bot integration confirmed, Chatwoot filters on its end
- `chatwoot_conversation_id` patched into session state before every turn
- `set_conversation_pending` called after every `send_text` (skipped when `escalated=True`)
- `_maybe_escalate` is a safety net — only fires if escalation tool ran before conversation ID was in state
- Route A (list reply): product picked deterministically, no LLM needed for selection
- Route B (text): catalog sent before `run_turn` so LLM knows menu was already deliverednow

---

### `apps/clients/chatwoot.py` ✅
- `_http` singleton — connection pool reused across all text/label calls
- Tenacity retry — 3 attempts, exponential backoff, 5xx only, never 4xx
- `set_conversation_pending` — soft failure (warning log), non-fatal
- `escalate_conversation` — toggle open → parallel label + private note + assign agent 180662

---

### `apps/clients/gcs.py` ✅
- `_client` module-level singleton
- No `blob.reload()` — `_guess_content_type` handles content type
- Sync SDK called via `asyncio.to_thread` in caller (`_deliver_media`)

---

### `apps/runner.py` ✅
- `InMemorySessionService` hot layer — zero network latency on every turn
- `VertexAiSessionService` cold layer — loaded once per session, flushed in background
- `copy.deepcopy(_DEFAULT_STATE)` — each session gets independent list instances
- `patch_session_state` — direct dict write for webhook-layer flags (no LLM involvement)
- **Verify:** after first live turn, check Vertex console to confirm `update_session(state=)` kwarg works for your ADK version

---

### `apps/prompts/khind_assembler.py` ✅
- `get_khind_instruction(context=None)` — correct ADK callable signature
- Reads `context.state` via `getattr` with fallback — safe if context is None
- Stage → fragment selection correct

---

### `apps/prompts/khind_prompts.py` ✅
- `GCS_KHIND_BUCKET` dead code removed (Round 11)
- All 8 product USPs in Bahasa Melayu
- Closing form template embedded verbatim — LLM instructed to send unchanged

---

### `apps/tools/session_tools.py` ✅
All tools correct. `tool_context` first positional arg. Stage machine logic clean.

---

### `apps/tools/rag_tool.py` ✅
Async. `asyncio.to_thread` for sync Vertex SDK. Cache keyed by `rag_{generation}_{hash}`.
## optional to use sematic caching 
---

### `apps/tools/escalation_tool.py` ✅
Async. Reads `chatwoot_conversation_id` from state. Calls Chatwoot directly. Sets `escalated=True` regardless of Chatwoot outcome.

---

### `apps/services/product_catalog.py` ✅
`resolve_product_selection` returns `None` for unknown row IDs — webhook discards silently.

---

### `apps/services/media_delivery.py` ✅
Reads live from GCS `list_blobs`. `already_sent` guard skips GCS call on repeat. Delivers incomplete set if files missing.

---

## Issues — All Resolved

| # | Issue | Fixed |
|---|---|---|
| B1 | `_DEFAULT_STATE` shallow copy | `copy.deepcopy` |
| B2 | Shared session fallback | Returns `""`, discarded |
| B3 | `False` in multipart | `"false"` string |
| B4 | Unknown list row falls to Route B | Early return |
| B5 | Lambda state mutation thread-unsafe | `update_session(state=snapshot)` |
| Q1–Q4 | httpx/GCS client per call, no retry, logging | Singletons + tenacity + lifespan |
| Q5–Q8 | Catalog timing, outgoing filter, tool_context | All fixed |
| M1–M4 | Session store, escalation, bot gate, conversation ID | All fixed |
| ENV1–2 | Wrong GCS key, wrong corpus ID | Fixed in `.env` |
| R1 | `_is_outgoing` dead code | Removed — Agent Bot confirmed |
| W3 | `GCS_KHIND_BUCKET` dead code | Removed |

---

## ⚠️ Still Needs Action

| # | What | How |
|---|---|---|
| W1 | Verify Vertex session flush | After first live turn → check Vertex AI Agent Engine console → session state should be there |
| W2 | `max_output_tokens=250` may truncate form | If customer reports cut-off form, change to `400` in `apps/agent.py` |
| W4 | `washer_dryer_11_7` 2nd image | Upload `2.jpeg` to `gs://khind_2028/Mesin basuh siap kering - Washer & Dryer 2-in1 Photo/` |

---

## Test Plan

### Tier 1 — Unit (no credentials needed)

```
tests/test_webhook_helpers.py   — _extract_session_id, _extract_list_row, _extract_inbound_text
tests/test_session_tools.py     — set_product_interest, advance_purchase_stage, save_application_details
tests/test_assembler.py         — get_khind_instruction per stage
tests/test_product_catalog.py   — resolve_product_selection
tests/test_media_delivery.py    — get_initial_media_plan with mock GCS
```

### Tier 2 — Integration (needs GCS creds)
```
tests/test_gcs_integration.py   — real download_bytes from khind_2028 bucket
```

### Tier 3 — Agent Behaviour (needs Gemini + Vertex)

| Input | Expected tool call | Expected state |
|---|---|---|
| "hi nak tanya pasal peti sejuk" | none | `stage=discovery` |
| `[PRODUCT_SELECTED:chillmaster_592l]` | `set_product_interest` | `stage=product` |
| "berapa harga?" | `query_product_info` | RAG cache hit |
| confirms postcode | `advance_purchase_stage` | `stage=qualification` |
| "nak jumpa manusia" | `escalate_to_live_agent` | `escalated=True` |
| fills all 11 form fields | `save_application_details` | `application_complete=True` |

---

## Debug Playbook

| Symptom | Check |
|---|---|
| Bot not replying | "ADK Runner initialised" in startup log? `GOOGLE_APPLICATION_CREDENTIALS` valid? |
| Wrong RAG results | `settings.vertex_rag_corpus` == `2305843009213693952`? |
| Product tap does nothing | Log raw payload — which field has the row ID? |
| USP repeated | `pitched_products` in state after first pitch? |
| Media not sending | `initial_media_sent_products` already has the key? GCS creds valid? |
| Escalation, no assignment | `CHATWOOT_HUMAN_AGENT_ID=180662` in `.env`? Log: "handed to human"? |
| Bot still replies after escalation | Expected — `escalated=True` keeps status `"open"`, bot gate off |
| Sessions gone after restart | Expected — cold load from Vertex on first message, then memory |

---

## Reference

### Product Keys
| Key | Product |
|---|---|
| `chillmaster_592l` | ChillMaster 592L |
| `chillmaster_lite_480l` | ChillMaster Lite 480L |
| `chillmaster_x_466l` | ChillMaster X 466L |
| `washer_dryer_11_7` | Washer Dryer 11KG/7KG |
| `front_load_9kg` | Front Load Washer 9KG |
| `ecowash_top_15kg` | EcoWash Top Load 15KG |
| `drymaster_9kg` | DryMaster Heat Pump 9KG |
| `aircond_kool_series` | KHIND KOOL Series Aircond |

### RAG Corpus
`projects/prudential-poc-484904/locations/asia-southeast1/ragCorpora/2305843009213693952`

### `.env` (Template / Reference)
```env
GOOGLE_CLOUD_PROJECT=your-gcp-project-id
GOOGLE_CLOUD_LOCATION=asia-southeast1
GOOGLE_GENAI_USE_VERTEXAI=1
LLM_MODEL=gemini-2.5-flash
RAG_CORPUS_NAME=projects/your-gcp-project-id/locations/asia-southeast1/ragCorpora/your-corpus-id
VERTEX_AI_AGENT_ENGINE_ID=your-agent-engine-id
GOOGLE_APPLICATION_CREDENTIALS=your-service-account-key.json
GCS_BUCKET=khind_2028
CHATWOOT_BASE_URL=https://app.chatwoot.com
CHATWOOT_API_TOKEN=your_chatwoot_api_token
CHATWOOT_ACCOUNT_ID=your_account_id
CHATWOOT_WEBHOOK_SECRET=your_webhook_secret
CHATWOOT_HUMAN_AGENT_ID=your_agent_id
PORT=8081
DEV_MODE=true
```

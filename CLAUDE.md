# KHIND WhatsApp sales agent

Google ADK 1.31 agent (`apps/agent.py`, Gemini 2.5 Flash on Vertex AI) behind a FastAPI
Chatwoot webhook (`apps/main.py`, `apps/webhook.py`). There is no test suite yet. Check scripts
from the 2026-09-24 session live in `handoff/verification/`. The ADK Web smoke-test package for
Astra computer use (62 cases, v2) lives in `handoff/smoke-test/`. The previous run (v1, 2026-09-20)
is in `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`.

## Sales flow (updated 2026-09-24)

Strictly linear, one step at a time:

1. Greeting and the 8-product list (stage `discovery`).
2. Product pick: `set_product_interest` moves the stage to `location`. The webhook sends 2 images
   and 1 video once per product, then one text message: the approved USP on top and the postcode
   and area question below. Code inserts the USP; the model only writes the question.
3. Coverage is checked against the fixed lists in the coverage fragment, not RAG.
   - Not covered: `escalate_to_live_agent("coverage-unsupported-alternative")`, then the "nanti" line.
   - Covered: `advance_purchase_stage()` (location to qualification), then the covered line and
     "bekerja sekarang?".
   - Unclear area (only a state, or a Sabah/Sarawak postcode without a town): ask for the town.
4. Not working (including students, pensioners, "kawan yang kerja nak ambil"):
   `escalate_to_live_agent("not-working")` plus one polite line. Working (including self-employed
   and gig work): the approved RM1 line "Pendaftaran hanya RM1, tiada bayaran lain sekarang. Jom
   semak kelayakan dulu?" This working/not-working split still needs the user's confirmation.
5. Customer agrees: `mark_application_form_sent()`, the fixed BORANG once, then
   `save_application_details` asks only for missing fields.

At any step, a product question gets a 1-2 sentence `query_product_info` answer, then the pending
step's question again. Naming another product calls `set_product_interest` (USP and media once)
and keeps the current stage. There is no Q&A stage and no payslip question any more.

## Where the flow is enforced

- `apps/tools/session_tools.py`
  - `set_product_interest`: moves `discovery`/`product` to `location`; later stages stay put. On a
    first pitch it queues the key in state `pending_usp_products` and returns
    `usp_sent_automatically` plus a `reply_rule`. It never returns the USP text.
  - `advance_purchase_stage`: errors when no product is set. It treats a legacy `product` stage
    (or `discovery` with a product) as `location`, so it always lands on `qualification`.
- `apps/prompts/khind_assembler.py`: no product gives the discovery fragment;
  `qualification`/`form` gives closing; anything else gives coverage.
- `apps/prompts/khind_prompts.py`: core rules (section "Aliran Jualan", the 1-8 product key map),
  the discovery, coverage and closing fragments, and `HANDOFF_FALLBACK_LINES`. All fixed
  customer-facing text lives here.
- `apps/services/replies.py`
  - `insert_pending_usp` (after-model callback): puts each pending USP, word for word, on top of
    the turn's first text reply. It strips any product feature block the model wrote itself.
  - `build_reply` (used by `run_turn`): keeps text written alongside tool calls, skips exact
    repeats, allows one handoff line per turn, and falls back to the label's fixed line.
- `apps/agent.py`: registers the callback; `max_output_tokens=2048`, `thinking_budget=1024`.
- `apps/webhook.py`: media first (waits at most 20 s), then text, then `set_conversation_pending`.
  An upload that finishes late sets pending again, unless the turn escalated.
- `apps/tools/escalation_tool.py`: labels are `coverage-unsupported-alternative`, `not-working`,
  `human-required`, `angry-customer`, `rag-error`. `no-payslip-alternative` is gone.

## Easy to get wrong

- ADK rebuilds the instruction before every model call. A tool that changes `purchase_stage` shows
  the next stage's fragment later in the same turn. That is why the covered line lives in the
  closing fragment, not the coverage fragment.
- `is_final_response()` drops text the model writes in the same step as a tool call. Always build
  replies with `build_reply`.
- Do not hand the model USP text to copy. In stored dev sessions it paraphrased the USP every time,
  and in tests it sometimes wrote a second USP with claims not in the approved text.
- Gemini 2.5 counts thinking tokens against `max_output_tokens`. Keep the thinking budget capped.
- `CLOSING_FRAGMENT_RAW` is an f-string, so literal braces added to it must be doubled.
- Local run from the repo root: `adk api_server --port 8000 --session_service_uri memory:// .` (or
  `adk web .`). The app name is `apps`. The server caches the agent, so restart it after edits.
  It shows the real reply text but not media. Without `memory://`, sessions go into
  `apps/.adk/session.db`. Stop it with `pkill -f "[a]dk api_server"` so pkill does not match itself.

## Open issues (as of 2026-09-24; update as they are fixed)

- Smoke test v2 (2026-09-24, Astra in ADK Web): 53 of 62 rows pass, no regressions against
  2026-09-20. Failing rows are A3, B10, B11, C2, D4, D5, D6, E4 and G6. Results, fix hypotheses and
  next steps are in `handoff/2026-09-24-khind-sales-flow.md`.

- The Chatwoot webhook fails on every message under ADK 1.31. `apps/runner.py` calls async session
  methods without `await`, so the first `patch_session_state` raises. Even when awaited,
  `get_session` returns a copy, `VertexAiSessionService` has no `update_session`, and
  `VERTEX_AI_AGENT_ENGINE_ID` in `.env` is never read. After the fix, check that the catalog menu
  and the model's own numbered list do not both reach the customer.
- RAG prices are unreliable. Answers mix figures from other products' documents or quote figures
  that are not in the corpus. Restricting results to the active product would help.
- In the form step the model repeated a customer's name, despite the rule against echoing details.
- The `not-working` label must be created in Chatwoot so these handoffs show in filters.
- `customer_location` is never written, so the handoff note shows "-". `escalated` never resets.
- `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.

## History

- 2026-09-24: sales flow rewritten to product, location, kerja, RM1, form. Details, verification
  results and next steps: `handoff/2026-09-24-khind-sales-flow.md`.

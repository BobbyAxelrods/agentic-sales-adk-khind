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
3. Coverage is decided in code (`apps/services/coverage.py`) from KHIND's fixed lists, not by the
   model and not by RAG. The model passes what the customer wrote to
   `advance_purchase_stage(postcode, town, state)`, which returns a status:
   - `ok` (covered): location moves to qualification, then the covered line and "bekerja sekarang?".
   - `not_covered`: the tool itself hands the chat to an officer (label
     `coverage-unsupported-alternative`, same Chatwoot call as `escalate_to_live_agent`), then the
     model sends the "nanti" line. The model does not call `escalate_to_live_agent` for it.
   - `need_town` (Sabah/Sarawak without a town), `need_state` (a town with no state or postcode),
     or `need_location`: the agent asks the returned question. A Peninsular state alone is covered.
4. Not working (including students, pensioners, "kawan yang kerja nak ambil"):
   `escalate_to_live_agent("not-working")` plus one polite line. Working (including self-employed
   and gig work): the approved RM1 line "Pendaftaran hanya RM1, tiada bayaran lain sekarang. Jom
   semak kelayakan dulu?" The user confirmed this split on 2026-09-24.
5. Customer agrees: `mark_application_form_sent()`, the fixed BORANG once, then
   `save_application_details` asks only for missing fields. When it returns `complete`, the reply is
   the fixed `APPLICATION_COMPLETE_LINE`, which asks for the IC photos.

At any step, a product question gets a 1-2 sentence `query_product_info` answer, then the pending
step's question again. Before any pick, a question about one product is the pick: if the model
only searches, `query_product_info` picks the product in code. A fact missing from the documents
gets the fixed `KB_GAP_LINE` ("Pegawai kami akan sahkan …"), not a handoff; `rag-error` is only for
a failed retrieval. Naming another product, including one picked earlier, calls
`set_product_interest` (USP and media once) and keeps the current stage. There is no Q&A stage and
no payslip question any more.

## Where the flow is enforced

- `apps/tools/session_tools.py`
  - `set_product_interest`: moves `discovery`/`product` to `location`; later stages stay put. On a
    first pitch it queues the key in state `pending_usp_products` and returns
    `usp_sent_automatically` plus a stage-aware `reply_rule` (at the location step: check a place
    given in the same message). It never returns the USP text.
  - `advance_purchase_stage(postcode, town, state)`: the coverage check (see `coverage.py`). Errors
    when no product is set. Writes `customer_location` (read by the Chatwoot handoff note) and keeps
    a partial answer in `location_draft`, so "Kapit" joins an earlier "96800". Only the location
    step moves the stage (legacy `product`/`discovery` count as location). Later, a call with no
    place is a no-op. It is async: on `not_covered` it calls `escalation_tool.hand_off` and returns
    `escalated` and `label`.
  - `find_product_keys(text)`: the products named in free text (longest alias first, no bare
    numbers). `query_product_info` uses it to choose the document to search.
- `apps/services/coverage.py`: `check_coverage`, with the Sabah/Sarawak town lists, town aliases
  (KK, Mukah …), postcode ranges and state aliases. The lists are no longer in the prompt.
- `apps/tools/rag_tool.py`: searches only the corpus file of the product named in the query, else
  of the active product (`top_k=8`, the whole document); with no product, the whole corpus
  (`top_k=3`). `PRODUCT_DOCUMENTS` maps keys to file names; the newest duplicate wins. Only `ok`
  results are cached. With no active product, a query that names one product also picks it
  (`set_product_interest`) and the response has `product_selected`: in scripted runs the model
  sometimes searched without picking (E1, 3 of 10 runs after the rerun-2 prompt changes).
- `apps/prompts/khind_assembler.py`: no product gives the discovery fragment;
  `qualification`/`form` gives closing; anything else gives coverage. The Current State block has
  a `Pending step` line built from state (escalated, product, stage, form sent, form complete).
- `apps/prompts/khind_prompts.py`: core rules (section "Aliran Jualan", the 1-8 product key map,
  `PRODUCT_MENU`), the discovery, coverage and closing fragments, `HANDOFF_FALLBACK_LINES`, and the
  fixed questions and lines (`LOCATION_QUESTION`, `KB_GAP_LINE`, `APPLICATION_COMPLETE_LINE` …).
  All fixed customer-facing text lives here.
- `apps/services/replies.py`
  - `strip_personal_values` (after-model callback, first): removes the customer's name (full, and
    each capitalised name word), IC, phone numbers, email and address, as saved in
    `application_details` or passed to `save_application_details` in the same response. The
    model thanked customers by name in the form step in every scripted run before it. It edits the
    response in place and returns `None`, so the other callbacks still run.
  - `drop_text_beside_coverage_or_handoff_call` (after-model callback): removes text written in
    the same response as an `advance_purchase_stage` call (before the verdict exists) or an
    `escalate_to_live_agent` call (where the model once wrote its English reasoning, B6).
  - `insert_pending_usp` (after-model callback): puts each pending USP, word for word, on top of
    the turn's first text reply. It strips any product feature block the model wrote itself. On a
    plain pick it keeps only the question: `LOCATION_QUESTION` at the location step, else the
    model's closing question. A pick is not plain when `query_product_info` or
    `advance_purchase_stage` ran in the same turn; both set `reply_facts_invocation` to the turn's
    id. A turn that escalated gets no USP.
  - `fill_empty_handoff_reply` (after-model callback): a handoff turn whose final reply has no
    text gets the label's fixed line (`HANDOFF_FALLBACK_LINES`), in ADK Web too.
  - `build_reply` (used by `run_turn`): keeps text written alongside other tool calls (never beside
    a coverage or handoff call), skips exact repeats, and falls back to the label's fixed line. It
    reads the handoff from the tool results, so the coverage tool's handoff counts.
- `apps/agent.py`: registers the four callbacks, in that order; `max_output_tokens=2048`,
  `thinking_budget=1024`.
- `apps/webhook.py`: media first (waits at most 20 s), then text, then `set_conversation_pending`.
  An upload that finishes late sets pending again. A turn that escalated gets no media, as it gets
  no USP.
- `apps/tools/escalation_tool.py`: labels are `coverage-unsupported-alternative`, `not-working`,
  `human-required`, `angry-customer`, `rag-error`. `no-payslip-alternative` is gone. `hand_off` is
  shared by `escalate_to_live_agent` and `advance_purchase_stage`: it makes the Chatwoot call, sets
  `escalated` and `escalation_label`, and records the turn in `escalation_invocation`. A second
  handoff with the same label in the same turn is a no-op (`already_escalated`).

## Easy to get wrong

- ADK rebuilds the instruction before every model call. A tool that changes `purchase_stage` shows
  the next stage's fragment later in the same turn. That is why the covered line lives in the
  closing fragment, not the coverage fragment.
- `is_final_response()` drops text the model writes in the same step as a tool call. Always build
  replies with `build_reply`.
- Do not leave a required step to the model when code can do it. In rerun 2 the model skipped the
  escalate call after `not_covered` once (B12) and wrote its English reasoning beside it once
  (B6). That is why the coverage tool hands over itself.
- `advance_purchase_stage` is async, so offline checks call it through `asyncio.run`.
- Do not hand the model USP text to copy. In stored dev sessions it paraphrased the USP every time,
  and in tests it sometimes wrote a second USP with claims not in the approved text. After a pick
  it also adds praise or invented claims ("pilihan popular", "jimat elektrik sehingga 50%") in
  almost every reply, whatever the prompt says (0 of 15 clean on 2026-09-24). That is why
  `insert_pending_usp` keeps only the question on a plain pick.
- Gemini 2.5 counts thinking tokens against `max_output_tokens`. Keep the thinking budget capped.
- `KHIND_CORE_RAW` and the discovery, coverage and closing fragments are f-strings, so literal
  braces added to them must be doubled.
- The vertexai SDK's regional clients ignore `GOOGLE_CLOUD_LOCATION`; they read
  `GOOGLE_CLOUD_REGION` and default to us-central1. `vrag.list_files` then fails for the
  asia-southeast1 corpus, so `rag_tool` calls `vertexai.init` with the corpus's own region first.
- ADK's `State` is not a Mapping: `dict(state)` raises `KeyError: 0`. Use `state.to_dict()`.
- `after_model_callback` takes a list; ADK stops at the first callback that returns a response.
  A callback that must not stop the rest edits `llm_response` in place and returns `None`.
- Local run from the repo root: `adk api_server --port 8000 --session_service_uri memory:// .` (or
  `adk web .`). The app name is `apps`. The server caches the agent, so restart it after edits.
  It shows the real reply text but not media. Without `memory://`, sessions go into
  `apps/.adk/session.db`. Stop it with `pkill -f "[a]dk api_server"` so pkill does not match itself,
  and never in the same shell command as a restart: the restart text matches the pattern and pkill
  kills its own shell. For verification, run it on port 8001
  (`KHIND_API_BASE=http://127.0.0.1:8001` for `scenarios.py`) so ADK Web can stay on 8000.

## Open issues (as of 2026-09-24; update as they are fixed)

- Smoke test v2 (2026-09-24, Astra in ADK Web): 53 of 62 on `cc153b1`, then 58 of 62 on
  `de4f6c9` (rerun 2).
  - Rerun 2's 4 failures (B6, B12, D6, E4) are fixed in `e1a3458`. The next commit adds the PDPA
    guard, no media on a handoff turn, and the pick by search (E1). Offline checks and scripted
    real-Gemini chats pass (`handoff/verification/rerun2_fix_run_2026-09-24.txt`).
  - The tool contract changed, so the next Astra run covers all 62 rows. That run (rerun 3) is the
    last test, by the user's decision: its failures are recorded here, not fixed, and the PR follows
    whatever the result. Status and next steps: `handoff/2026-09-24-khind-sales-flow.md`.

- The Chatwoot webhook fails on every message under ADK 1.31. `apps/runner.py` calls async session
  methods without `await`, so the first `patch_session_state` raises. Even when awaited,
  `get_session` returns a copy, `VertexAiSessionService` has no `update_session`, and
  `VERTEX_AI_AGENT_ENGINE_ID` in `.env` is never read. After the fix, check that the catalog menu
  and the model's own numbered list do not both reach the customer.
- RAG corpus data (retrieval itself is now limited to the product's document):
  - `khind_acson_knowledge_base.md` and `khind_dhp90_drymaster_heatpump_dryer_knowledge_base.md`
    were each uploaded twice. The older copies (2026-09-12 03:15Z and 03:32Z) differ from the newer
    ones and should be deleted. Until then the code uses the newest.
  - The DryMaster document holds two conflicting price tables (RM85/month for 48 months, against
    RM105 for 48 and RM135 for 36). KHIND must confirm which is current.
  - The aircond document has no monthly price, so the agent sends the missing-fact line.
- In the form step the model lists the missing fields in the form layout, although the rule says
  not to resend the form. (Its name echo is now removed by `strip_personal_values`.)
- Route A of the webhook (a WhatsApp list pick) sets the conversation to pending after its text
  even when the chat was handed over; Route B does not.
- The `not-working` label must be created in Chatwoot so these handoffs show in filters.
- `escalated` never resets.
- The IC-photo step never ends: `webhook.py` drops messages that hold only images.
- A question with no product named and none active (for example "ada promosi?" at discovery)
  still searches the whole corpus.
- `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.

## History

- 2026-09-24: sales flow rewritten to product, location, kerja, RM1, form. Details, verification
  results and next steps: `handoff/2026-09-24-khind-sales-flow.md`.
- 2026-09-24 (later): the v2 smoke test was audited and its 9 failures fixed:
  - coverage decided in code;
  - retrieval limited to the product's document;
  - a pending-step line in the prompt;
  - the missing-fact line instead of a `rag-error` handoff;
  - a fixed form-complete line;
  - the first-pick guard.

  The escalation tool's `dict(state)` crash was also fixed.
- 2026-09-24 (rerun 2, 58 of 62): the audit confirmed all 4 failures. The fixes:
  - `advance_purchase_stage` hands an uncovered area to an officer itself;
  - text beside a coverage or handoff call is dropped;
  - the out-of-range rule names the 3 product categories;
  - the kerja and IC-photo questions carry an emoji, and every reply needs one.

  The audit note is in the Obsidian folder `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 2`.
- 2026-09-24 (after the rerun-2 fixes, user decisions):
  - code removes personal values from replies;
  - a turn that escalated gets no media;
  - `query_product_info` picks the product before any pick. After the rerun-2 prompt changes the
    model skipped that pick in E1 in 3 of 10 scripted runs (0 of 8 on the old code).

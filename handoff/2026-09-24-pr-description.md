## Summary

The KHIND WhatsApp sales agent now follows one linear flow: product, location, kerja, RM1,
form. Rules that the model kept breaking in tests are now enforced in code: coverage verdicts,
the approved USP text, handoffs for uncovered areas, and the removal of personal data from
replies. The 62-row ADK Web smoke test went from 53 to 58 to 62 of 62. Each run was audited
against `apps/.adk/session.db`.

## The flow

1. Greeting and the 8-product list.
2. Product pick (`set_product_interest`). The webhook sends 2 images and 1 video once per
   product. Code puts the approved USP on top of the reply. The model writes only the postcode
   and area question.
3. Coverage is decided in code (`apps/services/coverage.py`) from KHIND's lists, through
   `advance_purchase_stage(postcode, town, state)`:
   - covered: the covered line, then "bekerja sekarang?";
   - not covered: the tool hands the chat to an officer (`coverage-unsupported-alternative`)
     and the agent sends the "nanti" line;
   - `need_town`, `need_state` or `need_location`: the agent asks the returned question.
4. Not working (including students, pensioners, "kawan yang kerja nak ambil"): handoff with
   the `not-working` label. Working (including self-employed and gig work): the RM1 line.
5. The customer agrees: the BORANG once, then `save_application_details` asks only for the
   missing fields. When the form is complete, a fixed line asks for the IC photos.

At any step, a product question gets a 1-2 sentence answer from that product's own document,
then the pending question again. A fact that is not in the documents gets a fixed missing-fact
line, not a handoff.

## Where the rules are enforced

- `apps/services/coverage.py` (new): coverage from the Sabah and Sarawak town lists, town
  aliases, postcode ranges and state aliases.
- `apps/tools/session_tools.py`: stage moves, the coverage tool with its own handoff, and
  product names found in free text.
- `apps/tools/rag_tool.py`: search limited to the product's document. With no active product,
  a question that names one product also picks it.
- `apps/services/replies.py` (new): after-model callbacks that remove the customer's personal
  values, drop text written beside a coverage or handoff call, put the approved USP on top word
  for word, and fill an empty handoff reply. `build_reply` builds the WhatsApp text.
- `apps/webhook.py`: media first (at most 20 s), then text, then pending. A turn that handed
  over gets no media.
- `apps/prompts/`: all fixed customer-facing text in `khind_prompts.py`, stage fragments, and a
  "Pending step" line in the prompt.
- `apps/agent.py`: `thinking_budget=1024` and `max_output_tokens=2048` (Gemini 2.5 counts
  thinking tokens against the output limit).

## Commits

- `cc153b1` the linear flow.
- `de4f6c9` fixes for the 9 failures of the first v2 run (A3 B10 B11 C2 D4 D5 D6 E4 G6).
- `e1a3458` fixes for the 4 failures of rerun 2 (B6 B12 D6 E4).
- `04ec5c7` PDPA guard, no media on a handoff turn, and the pick by search (E1).
- The other commits change only docs (`CLAUDE.md`, `handoff/`), the audit scripts and `.gitignore`.

## Test results

| Run (2026-09-24) | Code | Astra (ADK Web) | Audit against `session.db` |
|---|---|---|---|
| v2, first run | `cc153b1` | 53 of 62 | 9 failures confirmed, fixed in `de4f6c9` |
| Rerun 2 | `de4f6c9` | 58 of 62 | 4 failures confirmed, fixed in `e1a3458` |
| Rerun 3 (last) | `04ec5c7` | 62 of 62 | all 62 passes confirmed |

- Offline checks on this branch: `handoff/verification/unit_checks.py` 158 of 158 and
  `webhook_order.py` 7 of 7.
- Scripted real-Gemini chats (`handoff/verification/scenarios.py`, 64 checks) passed twice
  before rerun 3.
- There is no automated test suite yet. The smoke-test package (62 rows, Astra prompt, guide) is
  in `handoff/smoke-test/`. The audit scripts are `extract_run.py`, `trace_run.py` and
  `check_run.py` in `handoff/verification/`.

## Open issues (not fixed in this PR)

- **The Chatwoot webhook fails on every message under ADK 1.31.** This is on `main` too:
  `apps/runner.py` calls async session methods without `await`. `get_session` returns a copy,
  `VertexAiSessionService` has no `update_session`, and `VERTEX_AI_AGENT_ENGINE_ID` is never
  read. Until this is fixed, the flow runs only in ADK Web.
- Found in the rerun-3 audit:
  - No retry on a transient Vertex AI error. G5's first attempt got a 502. On WhatsApp the
    customer would get the technical-problem line and must write again.
  - D2 ("Ada promosi ke sekarang?") got the missing-fact line, although the retrieved DryMaster
    text lists the RM1 processing fee and free delivery, installation, relocation, servicing and
    insurance.
  - C6 ("12") said "senarai produk kami" without showing the list.
- RAG corpus data:
  - `khind_acson_knowledge_base.md` and the DryMaster document were each uploaded twice. The
    older copies should be deleted. The code uses the newest.
  - The DryMaster document has two conflicting sources, for the price (RM85/month for 48 months,
    against RM105 for 48 and RM135 for 36) and for the warranty (a motor or a compressor
    warranty; 4 years on RTO, or 4 or 3 years by plan). KHIND must confirm which is current.
  - The aircond document has no monthly price.
- A missing-fact reply says that an officer will confirm, but it hands nobody the chat.
- In the form step the model sometimes lists the missing fields in the form layout (not seen
  in rerun 3).
- Webhook Route A (a WhatsApp list pick) sets the conversation to pending after a handoff;
  Route B does not.
- The `not-working` label must be created in Chatwoot.
- `escalated` never resets.
- The IC-photo step never ends: `webhook.py` drops messages that hold only images.
- A question with no product named and none active still searches the whole corpus.
- `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.
- The smoke test has no row for: a product question after the RM1 invite or during the form, a
  customer who declines the eligibility check, a comparison of two products, and a question with
  no product at discovery.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01XfM8uvzMzF6on23ZPaqkr6

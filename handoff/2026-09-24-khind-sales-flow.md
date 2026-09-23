# Handoff: KHIND sales flow (2026-09-24). Next session: audit and fix the smoke-test failures

## Where things stand

- **The v2 smoke test ran on 2026-09-24 through Astra in ADK Web.** Astra reports:

  | Rows run | Pass | Fail | Blocked | N/A | Pass rate |
  |---|---|---|---|---|---|
  | 62 | 53 | 9 | 0 | 0 | 85.5% |

  The 2026-09-20 run passed 26 of 52 rows.
  - Fixed since then: 15 rows.
  - Regressed: none.
- **Failing rows:** A3, B10, B11, C2, D4, D5, D6, E4, G6. The expected and actual behaviour for
  each is in Astra's report. Do not copy it here.
- **Astra's results bundle.** From Windows, the zip is at
  `C:\Users\User\Documents\Codex\2026-09-24\files-mentioned-by-the-user-khind\outputs\KHIND_Smoke_Test_Evidence_2026-09-24.zip`.
  From WSL, use
  `/mnt/c/Users/User/Documents/Codex/2026-09-24/files-mentioned-by-the-user-khind/outputs/`.
  An unzipped copy sits next to the zip in `KHIND_Smoke_Test_2026-09-24/`. It holds:
  - `README.md`, `KHIND_Smoke_Test_Report.md` (failure table and v1 comparison), and
    `Analysis and Findings.md`;
  - `KHIND_Agent_Smoke_Test_Results_2026-09-24.csv`, with columns G, I, J and K filled;
  - `Evidence/`, with one JSON file per row plus warm-ups, holding the prompt, chat, tool panels,
    State and the raw final event;
  - `Screenshots/`.
  - Astra's working files are in `../work/`.
- **Results are CSV only.** The v2 xlsx, with its Summary formulas, has not been filled in.
- **The run in the session database.** `apps/.adk/session.db` holds 37 new sessions and 83 user
  messages, exactly as planned.
  - The run went from 2026-09-24 04:05:42 to 04:28:37 local time (MYT, UTC+8), which is
    2026-09-23 20:05:42Z to 20:28:37Z.
  - Run A is session `3e8f3b32-9e2e-4e60-9429-c1ced65f0a7f`. F6 resumed it.
- **ADK Web is still running.** The user started it (`adk web --port 8000 .`, pid 138908 at the
  time of writing). Leave it for reruns, or ask the user to stop it.
- **The tested code is uncommitted.** It is the working tree on branch `chore/gitignore-graphify`.

## Activities for the next session, in order

### 1. Decide with the user first

1. **Commit the tested code before changing anything.** Then the 53/62 result maps to a commit.
   Suggest a feature branch such as `feat/linear-sales-flow`, and only commit with the user's OK.
2. **Ask where the record should live.** The v1 bundle is in
   `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`. Ask before copying Astra's bundle there
   as `2026-09-24 - KHIND Linear Flow Smoke Test/`.
3. **Pensioners and self-employed people** are still unconfirmed. F9 and F10 passed only under the
   sheet's assumptions.
4. **Ask whether rag-error handoffs are wanted.** In E1 and G6 the agent handed off with
   `rag-error` when the knowledge base simply lacked the fact. `rag-error` is meant for retrieval
   failures, and this ends the sale on a price question. Ask whether the agent should instead say
   an officer will confirm, and carry on with the pending step.

### 2. Audit Astra's verdicts (Claude)

5. **Load the evidence.** Use the results CSV, then open `apps/.adk/session.db` read-only:
   `file:apps/.adk/session.db?mode=ro`. Take only sessions created after 2026-09-23 20:05Z. Parse
   `events.event_data` with `google.adk.events.Event.model_validate`, and map sessions to rows
   by order and first message.
6. **Re-check all 9 failures.** Then spot-check passes Astra could have missed:
   - B12: USP optional, one handoff line.
   - F1-F3 and F7-F9: double handoff lines, labels.
   - A7: form lines.
   - A8-A10 and F6: PDPA.
   - Every reply with a figure: the `source` of each `query_product_info` chunk.

   `build_reply` in `apps/services/replies.py` shows what WhatsApp would have received.
7. **Record any disagreement with Astra,** and write it into the results before the next rerun.
8. **Optional.** Fill the v2 xlsx from the CSV (columns G, I, J, K) so its Summary and v1
   comparison compute. `build_smoke_test_v2.py` shows the layout. Use the `anthropic-skills:xlsx`
   skill.

### 3. Triage and fix (plan mode first)

9. **Confirm or reject each hypothesis** below from the evidence, then write the fix plan and get
   approval before editing.
10. **Implement the fixes.** Add each failing case to `handoff/verification/scenarios.py`, or to a
    real pytest suite (`tdd` skill), so it stays fixed. Re-run `unit_checks.py` and
    `webhook_order.py`.
11. **Rerun with Astra.** Include the failed rows plus a small regression sample: A1-A11 and B2.
    Filter the v2 CSV to those IDs and reuse `KHIND-Astra-ComputerUse-Prompt-v2.md` as is; it
    tells Astra to run the rows in the sheet. Restart ADK Web after code edits, because it caches
    the agent.
12. **Update** CLAUDE.md "Open issues", this file, and the Obsidian record.

## First hypotheses for the 9 failures (unverified, from Astra's report)

| ID | Severity (Astra) | Likely cause | Likely fix |
|---|---|---|---|
| A3 | Critical | RAG returns the ChillMaster Lite 480L document first; the 592L chunk has no price | Code: filter `query_product_info` results to the active product's source document, and say "pegawai akan sahkan" when nothing is left |
| B10 | Major | "Poskod 96800" alone was declared covered. 96800 is Kapit, which is NOT covered, so the verdict was wrong as well as premature | Prompt: a Sabah/Sarawak postcode alone is never enough. Or, better, a deterministic coverage tool built from the lists |
| B11 | Critical | The "first pick in this turn: reply ONLY with the location question" rule overrode the area the customer had given | Prompt: check for an area in the same message before asking; reword the coverage fragment |
| C2 | Major | "Ada aircond tak?" was read as browsing, not a pick (it also failed on 2026-09-20) | Prompt: question-form mentions count as a pick; add examples to the discovery fragment |
| D5 | Critical | After the menu was resent in D4, the agent forgot that the location step was pending | Assembler: put an explicit "pending step" line in the Current State block; core rule: resending the list keeps the pending step |
| G6 | Major | Switching back to an already pitched product did not call `set_product_interest`, so State kept `front_load_9kg`; then a `rag-error` handoff | Prompt: any product mention, including earlier ones, calls the tool. Handoff policy per decision 4 above |
| D4 | Minor | The list was resent flat, not in 3 groups | Prompt: reuse the grouped list text exactly |
| D6 | Minor | It referred to a list it did not show, and said KHIND does not sell TVs at all | Prompt wording |
| E4 | Minor | The completion message in A10 ends with a statement | Decide whether a closing statement is fine after completion; if so, fix the test, not the agent |

## Status of the code change

- The linear WhatsApp sales flow is implemented: product, location, kerja, RM1 promo, form. It
  passes offline checks, scripted real-Gemini chats and, apart from the rows above, the smoke test.
- Uncommitted work:
  - 7 modified files under `apps/`;
  - new `CLAUDE.md` and `apps/services/replies.py`;
  - `handoff/`, with `verification/` and `smoke-test/`.
- `docs/project-brief/` was already untracked before this session. It belongs to the user, so
  leave it alone.
- Nothing reaches WhatsApp yet. The Chatwoot webhook crashes on every message because of a bug
  that predates this work (see CLAUDE.md). ADK Web does not use that path.

## Read these instead of re-deriving

- `CLAUDE.md`: the target flow, where each rule is enforced, pitfalls, and open issues.
- The smoke-test package `handoff/smoke-test/`:
  - the v2 xlsx and csv (62 cases);
  - `KHIND-Astra-ComputerUse-Prompt-v2.md` and `KHIND-Smoke-Test-Guide-v2.md`;
  - `build_smoke_test_v2.py`, which regenerates the form from `apps/prompts/khind_prompts.py`.
- The final plan and the user's decisions:
  `/home/risdin/.claude/plans/continue-plan-from-home-risdin-claude-pl-breezy-wolf.md`.
  The earlier as-is vs proposed comparison:
  `/home/risdin/.claude/plans/based-on-the-current-cheerful-wolf.md`.
- The v1 test and run: `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`.

## Changes made during implementation that the plan does not record

1. **Broader USP guard.** `insert_pending_usp` strips any feature block the model writes (a bold
   title followed by ✅ lines), then prepends the approved USP. The smoke test found no extra ✅
   lines, including the switch cases G5 and G7.
2. **Extra steering.** `set_product_interest` returns a `reply_rule` string, and the closing
   fragment has a "customer switched product" bullet.
3. **Late uploads keep the bot in charge.** When media outlasts the 20 s wait, the webhook sets
   the conversation to pending again once the upload finishes, unless the turn escalated.

## Verification before the smoke test

| Script (`handoff/verification/`) | Covers | Result |
|---|---|---|
| `unit_checks.py` | Session tools, assembler, USP callback and feature-block strip, `build_reply` | 45 of 45 pass |
| `webhook_order.py` | Send order on both routes, the 20 s bound, late re-pend, escalated turns | 7 of 7 pass |
| `scenarios.py` | 7 real-Gemini chats through `adk api_server` | 23 of 23 pass |

`scenarios.py` needs `adk api_server --port 8000 --session_service_uri memory:// .` running. ADK
Web uses the same port, so stop one before starting the other.

## Backlog after this round of fixes

1. **Fix the session layer** in `apps/runner.py` so the webhook runs (defects in CLAUDE.md). Then
   test on a real phone: media before text, handoff lines delivered, labels applied. Also look for
   a double product list: the webhook's catalog message plus the model's own list.
2. **Ops.** Create the `not-working` label in Chatwoot.
3. **Housekeeping.** `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.
4. **Test gaps** found after the run:
   - No case asks a product question after the RM1 invite or while the form is being filled.
   - No case covers a customer who declines the eligibility check.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, model
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`. LibreOffice is
  not installed.
- Stop dev servers with `pkill -f "[a]dk web"` or `pkill -f "[a]dk api_server"`. The brackets stop
  pkill from matching its own shell.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

## Suggested skills

- `anthropic-skills:xlsx`: to fill the v2 workbook from Astra's CSV and to regenerate filtered test
  sheets.
- `diagnose`: for each confirmed failure (reproduce, minimise, fix, regression test).
- `tdd`: to turn `handoff/verification/*.py` and the new failure cases into a pytest suite.
- `code-review`: to review the diff before committing.
- `graphify`: for codebase questions. `graphify-out/` predates this change, so refresh it first.

# Handoff: KHIND sales flow. Next session: Astra rerun 3 (all 62 rows, the last test), then push and open the PR

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions.

Rules, enforcement points and pitfalls are in `CLAUDE.md`; this file does not repeat them.

## Where things stand (2026-09-24, 11:00 MYT)

- **Branch** `feat/linear-sales-flow`, 6 commits ahead of `main`:
  - `7fa1a34`: gitignore for graphify;
  - `cc153b1`: the linear flow;
  - `de4f6c9`: fixes for the first run's 9 failures;
  - `d91a9ab`: the rerun-2 handoff;
  - `e1a3458`: the fixes for rerun 2's 4 failures;
  - the commit after it: the PDPA guard, no media on a handoff turn, and the pick by search (E1).
  The branch is not pushed and there is no PR. `docs/` is the user's and stays untracked.
- **ADK Web** runs as pid 156943, started at 07:57:43 MYT, so it still serves `de4f6c9`. It caches
  the agent. **It must be restarted before Astra runs.** Stop and start it in two separate
  commands (see CLAUDE.md).
- **Rerun 2 audit:**
  - all 4 failures are confirmed, and no pass is overturned (58/62);
  - B6 was worse on WhatsApp than in ADK Web: `build_reply` would have sent only the English
    reasoning;
  - every figure traces to the active product's document;
  - the only text written beside a tool call in the whole run was B6's.
- **Obsidian records** (in `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`):
  - the folder `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 2/` holds Astra's bundle,
    `Inputs/` (the sheet Astra ran, as of `de4f6c9`) and `Claude Audit of Astra Verdicts.md`;
  - the zip `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 2.zip` sits next to it.
- **User decisions (2026-09-24):**
  - E4: 📸 is added to `IC_PHOTO_QUESTION` and 😊 to `KERJA_QUESTION`. Every reply needs an emoji;
    bold is only for key terms.
  - B6/B12: `advance_purchase_stage` hands an uncovered area to an officer itself.
  - `TOWN_QUESTION` and `POSTCODE_QUESTION` are approved as written.
  - Git: commit when the checks pass. Push and open a PR to `main` only after Astra's next rerun.
  - PDPA: code removes the customer's personal values from replies.
  - Media: a turn that escalated gets no media.
  - Rerun 3 is the last test. Whatever fails is recorded as an open issue, with evidence. It is not
    fixed, and there is no rerun 4 before the PR.
- **The fixes** (details in CLAUDE.md, "Where the flow is enforced"):
  - `advance_purchase_stage` is async. On `not_covered` it calls `escalation_tool.hand_off`, the
    same code as `escalate_to_live_agent`. A repeated handoff with the same label in the same turn
    is a no-op.
  - `drop_text_beside_coverage_or_handoff_call` also drops text beside `escalate_to_live_agent`.
  - The new callback `fill_empty_handoff_reply` gives a silent handoff turn the label's fixed line.
  - `build_reply` never sends text beside a coverage or handoff call, and it reads the handoff from
    the tool results.
  - The new callback `strip_personal_values` runs first. It removes the name, IC, phone numbers,
    email and address the customer gave, edits the response in place, and returns `None`.
  - `webhook._deliver_media_before_text` skips media on a turn that escalated.
  - `query_product_info` picks the product when none is active and the query names exactly one.
    After the first commit's prompt changes, the model skipped that pick in E1 in 3 of 10
    scripted runs; on the old code it never did (0 of 8).
  - Prompts:
    - the coverage fragment and the escalation triggers no longer ask for an escalate call on
      `not_covered`;
    - the D6 rule names the 3 categories and says "senarai" only with the list;
    - the style rule asks for an emoji in every reply.
- **Verification** (`handoff/verification/rerun2_fix_run_2026-09-24.txt` has every run):
  - `unit_checks.py`: 158 of 158 (40 new);
  - `webhook_order.py`: 7 of 7;
  - `scenarios.py`, real Gemini on port 8001, on the final code: 64 of 64 twice;
  - new scenarios: `labuan` (B6) and `product_uncovered` (B12). The tool made the handoff, the
    model made no escalate call, and the reply was exactly the not-covered line;
  - the form step no longer echoes the name ("Terima kasih! 😊" where earlier runs said ", Ali!");
  - E1 alone passed 8 of 8, once through the code pick.
- **Smoke-test package updated for the new contract**, and the sheet regenerated:
  - B2, B5-B7 and B12 now expect the handoff in the `advance_purchase_stage` response, and no
    escalate call;
  - B6, D6 and E4 have new criteria;
  - the Reference sheet adds the postcode, kerja and IC-photo questions;
  - the Astra prompt changes rule 7, the not-a-failure list and the known issues, and adds a
    comparison with rerun 2;
  - the guide's watch list is refreshed.

## Decisions to ask the user first

None are open. The user settled the PDPA guard and the media question on 2026-09-24, and made
rerun 3 the last test.

## Activities for the next session, in order

1. Ask the user to restart ADK Web (it still serves `de4f6c9`), then run Astra on **all 62
   rows**, because the tool contract changed. Use the regenerated
   `KHIND_Agent_Smoke_Test_Prompts_v2.csv` and the updated `KHIND-Astra-ComputerUse-Prompt-v2.md`.
   **This is the last test:** record every failure; do not fix it and do not rerun.
2. Audit rerun 3 as for rerun 2:
   - dump it with `.venv/bin/python handoff/verification/extract_run.py <start UTC> <out_dir>`;
   - compare it with Astra's CSV;
   - trace every figure to the chunk `source`;
   - look for text beside tool calls;
   - check the handoff rows: B2, B5-B7, B12, F1-F3, F7-F9.
3. File the bundle in Obsidian the same way (its own dated folder, `Inputs/`, zip, audit note).
4. Record every failure and audit finding, with evidence, in CLAUDE.md "Open issues", this file
   and the Obsidian audit note. Commit.
5. Push `feat/linear-sales-flow` and open the PR to `main`, whatever rerun 3's result. List the
   open failures in the PR description. If a code review is run first, note its findings in the PR
   as well; do not fix them.

## Backlog (details in CLAUDE.md "Open issues")

1. `apps/runner.py`: the session layer, so the Chatwoot webhook works; then a real phone test.
2. Create the Chatwoot `not-working` label.
3. RAG corpus:
   - delete the older duplicate files;
   - KHIND must confirm the DryMaster price;
   - the aircond monthly price is missing.
4. The IC-photo step never ends, because the webhook drops messages that hold only images.
5. `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.
6. A missing-fact reply promises that an officer will confirm, but it hands nobody the chat (seen
   in D7 for a discount request). Decide whether officers see these chats.
7. Webhook Route A (a WhatsApp list pick) sets the chat to pending after a handoff; Route B does
   not.
8. In the form step the model re-lists the missing fields in the form layout.
9. **Test gaps**, with no row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls and open issues.
- The rerun-2 audit: `Claude Audit of Astra Verdicts.md` in the Obsidian Rerun 2 folder above.
- Commits:
  - `git show d91a9ab` (rerun 2 findings);
  - `git show e1a3458` (the rerun-2 fixes);
  - the commit after it (PDPA guard, media, pick by search);
  - `git show de4f6c9` (the first fix round).
- The test tools in `handoff/verification/`:
  - `unit_checks.py`: 158 checks;
  - `webhook_order.py`;
  - `scenarios.py`: 17 scenarios, 64 checks;
  - `extract_run.py`;
  - the run logs `fix_run_2026-09-24.txt` and `rerun2_fix_run_2026-09-24.txt`.
- The smoke-test package in `handoff/smoke-test/`:
  - the builder;
  - the v2 csv/xlsx;
  - the guide;
  - `KHIND-Astra-ComputerUse-Prompt-v2.md`.

## Suggested skills

- `code-review`: review the branch before pushing or opening the PR.
- `claude-md-management:revise-claude-md`: update CLAUDE.md after rerun 3.
- `simple-english`: the handoff, CLAUDE.md and the Obsidian notes are written in short, plain
  English; keep that style.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, and
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`.
- For verification, run the API server on port 8001 (`--session_service_uri memory://`); ADK Web
  stays on 8000.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

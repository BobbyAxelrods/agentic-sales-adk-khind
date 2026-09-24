# Handoff: KHIND sales flow. Next session: Astra rerun 3 (all 62 rows), then push and open the PR

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions.

Rules, enforcement points and pitfalls are in `CLAUDE.md`; this file does not repeat them.

## Where things stand (2026-09-24, 09:50 MYT)

- **Branch** `feat/linear-sales-flow`, 5 commits ahead of `main`:
  - `7fa1a34`: gitignore for graphify;
  - `cc153b1`: the linear flow;
  - `de4f6c9`: fixes for the first run's 9 failures;
  - `d91a9ab`: the rerun-2 handoff;
  - the commit after it: the fixes for rerun 2's 4 failures.
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
- **The fixes** (details in CLAUDE.md, "Where the flow is enforced"):
  - `advance_purchase_stage` is async. On `not_covered` it calls `escalation_tool.hand_off`, the
    same code as `escalate_to_live_agent`. A repeated handoff with the same label in the same turn
    is a no-op.
  - `drop_text_beside_coverage_or_handoff_call` also drops text beside `escalate_to_live_agent`.
  - The new callback `fill_empty_handoff_reply` gives a silent handoff turn the label's fixed line.
  - `build_reply` never sends text beside a coverage or handoff call, and it reads the handoff from
    the tool results.
  - Prompts:
    - the coverage fragment and the escalation triggers no longer ask for an escalate call on
      `not_covered`;
    - the D6 rule names the 3 categories and says "senarai" only with the list;
    - the style rule asks for an emoji in every reply.
- **Verification** (`handoff/verification/rerun2_fix_run_2026-09-24.txt`):
  - `unit_checks.py`: 138 of 138 (20 new);
  - `webhook_order.py`: 7 of 7;
  - `scenarios.py`, real Gemini on port 8001: run 1 62 of 62; run 2 62 of 63;
  - new scenarios: `labuan` (B6) and `product_uncovered` (B12). Both passed twice: the tool made
    the handoff, the model made no escalate call, and the reply was exactly the not-covered line.
  - Run 2's only failure is a PDPA check added after run 1. See decision 1 below.
- **Smoke-test package updated for the new contract**, and the sheet regenerated:
  - B2, B5-B7 and B12 now expect the handoff in the `advance_purchase_stage` response, and no
    escalate call;
  - B6, D6 and E4 have new criteria;
  - the Reference sheet adds the postcode, kerja and IC-photo questions;
  - the Astra prompt changes rule 7, the not-a-failure list and the known issues, and adds a
    comparison with rerun 2;
  - the guide's watch list is refreshed.

## Decisions to ask the user first

1. **PDPA name echo in the form step (open issue, Critical under row A8).**
   - Evidence: the scripted happy path thanked the customer by name in both runs today ("Terima
     kasih, Ali!" and "Terima kasih, Ali bin Abu! 😊"), and in the 2 earlier scripted runs.
   - In the same reply the model also re-lists the missing fields in the form layout.
   - Astra's A8 passed in rerun 2, so the echo is intermittent. It can still fail rerun 3.
   - Recommendation: a code guard. Either remove personal values from the reply in a turn where
     `save_application_details` ran, or reply with a fixed line that names the missing fields.
     The fixed line is new wording, so the user must approve it.
2. **Media on a handoff turn.** On a first pick with an uncovered area (B12), the webhook still
   sends the product's 2 images and 1 video: `_deliver_media_before_text` does not check
   `escalated`. Should a turn that escalated skip the media? ADK Web cannot show this; check it in
   `webhook_order.py`.

## Activities for the next session, in order

1. Ask decisions 1 and 2. Implement what the user approves, with offline checks and two scenario
   runs, before the Astra run.
2. Ask the user to restart ADK Web, then run Astra on **all 62 rows**, because the tool contract
   changed. Use the regenerated `KHIND_Agent_Smoke_Test_Prompts_v2.csv` and the updated
   `KHIND-Astra-ComputerUse-Prompt-v2.md`.
3. Audit rerun 3 as for rerun 2:
   - dump it with `.venv/bin/python handoff/verification/extract_run.py <start UTC> <out_dir>`;
   - compare it with Astra's CSV;
   - trace every figure to the chunk `source`;
   - look for text beside tool calls;
   - check the handoff rows: B2, B5-B7, B12, F1-F3, F7-F9.
4. File the bundle in Obsidian the same way (its own dated folder, `Inputs/`, zip, audit note).
5. If rerun 3 passes: run the `code-review` skill on `main..feat/linear-sales-flow`, then push and
   open the PR. The user approved this order.
6. Update CLAUDE.md "Open issues", this file and the Obsidian record, and commit.

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
7. **Test gaps**, with no row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls and open issues.
- The rerun-2 audit: `Claude Audit of Astra Verdicts.md` in the Obsidian Rerun 2 folder above.
- Commits:
  - `git show d91a9ab` (rerun 2 findings);
  - the fix commit after it;
  - `git show de4f6c9`.
- The test tools in `handoff/verification/`:
  - `unit_checks.py`: 138 checks;
  - `webhook_order.py`;
  - `scenarios.py`: 17 scenarios, 63 checks;
  - `extract_run.py`;
  - the run logs `fix_run_2026-09-24.txt` and `rerun2_fix_run_2026-09-24.txt`.
- The smoke-test package in `handoff/smoke-test/`:
  - the builder;
  - the v2 csv/xlsx;
  - the guide;
  - `KHIND-Astra-ComputerUse-Prompt-v2.md`.

## Suggested skills

- `code-review`: review the branch before pushing or opening the PR.
- `tdd`: for the PDPA guard, if the user approves it. Write the echo check first.
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

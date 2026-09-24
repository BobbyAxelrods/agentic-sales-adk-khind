# Handoff: KHIND sales flow. Next session: fix B6, B12, D6 and E4 from Astra's rerun (58/62)

Earlier versions of this file are in git history: `cc153b1` (the first v2 run) and `de4f6c9`
(the fix round). Rules, enforcement points and pitfalls are in `CLAUDE.md`; this file does not
repeat them.

## Where things stand (2026-09-24, 08:55 MYT)

- **Branch** `feat/linear-sales-flow`, 3 commits ahead of `main`:
  - `7fa1a34`: gitignore for graphify;
  - `cc153b1`: the linear flow; the first v2 run passed 53/62 on it;
  - `de4f6c9`: fixes for that run's 9 failures.
  The branch is not pushed and there is no PR. `docs/` is the user's and stays untracked.
- **ADK Web** runs as pid 156943, restarted by the user at 07:57:43 MYT, after `de4f6c9`, so it
  serves the fixed code. It caches the agent: restart it after every code change. Stop and start
  it in two separate commands (see CLAUDE.md).
- **Astra's rerun of all 62 rows on `de4f6c9` is done:** 58 Pass, 4 Fail (0 Critical, 2 Major,
  2 Minor). The run went from 08:00:35 to 08:36:16 MYT (00:00:35Z to 00:36:16Z): 37 sessions and
  83 user turns in `apps/.adk/session.db`. Run A (with F6) is session `29551bf8`.
  - Fixed since the first run: A3, B10, B11, C2, D4, D5, G6.
  - Newly failing: B6 and B12 (Major).
  - Still failing: D6 and E4 (Minor).
- **Astra's bundle for the rerun** is under
  `/mnt/c/Users/User/Documents/Codex/2026-09-24/files-mentioned-by-the-user-khind/outputs/`:
  folder `KHIND_Smoke_Test_2026-09-24_Rerun2/` (report, results CSV, Evidence, Screenshots) and
  `KHIND_Smoke_Test_Evidence_2026-09-24_Rerun2.zip`. It is not copied to Obsidian yet.
- **Records:**
  - the first run and its audit are in the Obsidian folder
    `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/2026-09-24 - KHIND Linear Flow Smoke Test/`,
    in `Claude Audit of Astra Verdicts.md`;
  - the fix-round verification is `handoff/verification/fix_run_2026-09-24.txt`.
- **Uncommitted:** this file.

## The 4 rerun failures: evidence and fix direction

Only B6 and B12 were checked in `session.db` for this handoff; no full audit yet. Astra's verdicts
are in the rerun report. Find a session by its first message with
`.venv/bin/python handoff/verification/extract_run.py 2026-09-24T00:00:00Z <out_dir>`.

| Row | What happened (checked in session.db) | Fix direction (to confirm) |
|---|---|---|
| B6 (Major) | For "Poskod 87000, Labuan", `advance_purchase_stage` returned `not_covered`. The model then sent `escalate_to_live_agent` together with English reasoning text ("The tool output indicates … I need to call `escalate_to_live_agent` …"). `build_reply` treats text beside an escalate call as the handoff line and drops later text, so the customer got the reasoning, and the correct BM line in the next event was lost. The label and `escalated` were correct. | Do not trust text written beside an escalate call. Either extend `drop_text_beside_coverage_call` to escalate calls, so the text after the tool, or else the label's fallback line, is used; or let `build_reply` prefer the text after the call. Add a unit check for this sequence. |
| B12 (Major) | For "Nak peti ais 592, saya duduk Kapit Sarawak" the tools were `set_product_interest` then `advance_purchase_stage` (`not_covered`), but the model never called `escalate_to_live_agent`. No `escalated` in State, so the USP was also prepended. No handoff reached the officer. | Make the coverage handoff deterministic: `advance_purchase_stage` escalates itself on `not_covered`, reusing the escalation logic, labels and Chatwoot call. The model then writes only the not-covered line. This also removes the escalate call that caused B6 in the coverage path. |
| D6 (Minor) | The reply said "8 produk dalam senarai kami" without showing the list. That wording comes from the D6 core rule written in the fix round. | Rule wording: name the 3 categories (peti sejuk, mesin basuh & pengering, penyaman udara) and do not say "senarai" unless `PRODUCT_MENU` is shown. |
| E4 (Minor) | Style only. A4 has no *bold*. A11 and F6 end with the fixed IC-photo question and have no emoji. A10, the fixed completion line with 👍, passed. | User decision (below): add an emoji to `IC_PHOTO_QUESTION`, which is approved wording, and/or ask for bold and an emoji in every reply; or relax E4. |

## Decisions to ask the user first

1. **E4:** change the approved IC-photo question (e.g. add 📸) and make bold and an emoji
   mandatory, or relax the E4 criterion?
2. **B12/B6:** should `advance_purchase_stage` escalate by itself on `not_covered`? It changes
   the tool contract; the smoke sheet's B rows and CLAUDE.md need updating.
3. **Unapproved wording** (written in the fix round, not yet confirmed by the user):
   - `TOWN_QUESTION`: "Boleh kongsikan nama bandar atau kawasan pemasangan cik/tuan di {region}? 😊"
   - `POSTCODE_QUESTION`: "Boleh kongsikan poskod kawasan pemasangan cik/tuan? 😊"
4. **Obsidian:** copy the Rerun2 bundle as a subfolder of the 2026-09-24 folder, or as its own
   dated folder?
5. **Push and PR:** push `feat/linear-sales-flow` and open a PR to `main` after the next rerun?
   Also: commit this handoff file?

## Activities for the next session, in order

1. Ask decisions 1-5 above.
2. **Audit Rerun2 in full**, as for the first run:
   - dump the run with `extract_run.py`;
   - compare it with `KHIND_Agent_Smoke_Test_Results_2026-09-24_Rerun2.csv`;
   - trace every figure to the chunk `source`, `scope` and `products`;
   - spot-check passes (B-row handoff lines, PDPA rows A8-A10 and F6, first-pick replies);
   - write the audit note next to the copied bundle.
3. **Plan mode:** confirm the fix directions in the table above, then implement:
   - add regression checks to `handoff/verification/unit_checks.py`;
   - add real-Gemini scenarios to `scenarios.py`: Labuan, product + uncovered area in one
     message, TV/microwave, post-form emoji;
   - run on port 8001 with `KHIND_API_BASE=http://127.0.0.1:8001`, twice.
4. **Update the smoke sheet** in `handoff/smoke-test/build_smoke_test_v2.py` for any contract
   change (B2, B5-B7, B12 tool expectations; E4), then regenerate it with `uv`.
5. **Ask the user** to restart ADK Web, and run Astra on the B rows, D1-D7, E4 and a regression
   sample (A1-A11), or on all 62 rows if the tool contract changed.
6. **Update** CLAUDE.md "Open issues", this file, and the Obsidian record. Commit with the user's
   OK.

## Backlog (details in CLAUDE.md "Open issues")

1. `apps/runner.py`: the session layer, so the Chatwoot webhook works; then a real phone test.
2. Create the Chatwoot `not-working` label.
3. RAG corpus: delete the older duplicate files; KHIND must confirm the DryMaster price; the aircond
   monthly price is missing.
4. The IC-photo step never ends, because the webhook drops messages that hold only images.
5. `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.
6. **Test gaps**, with no row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls (vertexai region, `State.to_dict()`,
  callback order, pkill), and open issues.
- The approved plan and root causes of the fix round:
  `/home/risdin/.claude/plans/witty-tumbling-ladybug.md`.
- Commits: `git show de4f6c9` (the fix list is in the message) and `git show cc153b1`.
- Astra's rerun report and CSV: in the `KHIND_Smoke_Test_2026-09-24_Rerun2/` folder above. Its
  "Comparison with earlier run today" section lists the changed expectations.
- The first-run audit: `Claude Audit of Astra Verdicts.md` in the Obsidian folder above.
- The test tools in `handoff/verification/`:
  - `unit_checks.py`: 118 checks;
  - `webhook_order.py`;
  - `scenarios.py`: 15 scenarios;
  - `extract_run.py`;
  - `fix_run_2026-09-24.txt`.
- The smoke-test package in `handoff/smoke-test/`:
  - the builder;
  - the v2 csv/xlsx;
  - `KHIND-Astra-ComputerUse-Prompt-v2.md`, which Astra uses unchanged.

## Suggested skills

- `diagnose`: for B6 and B12. Reproduce them with `scenarios.py` on port 8001, minimise, fix, and
  add a regression check.
- `tdd`: to write the B6 (reasoning text beside an escalate call) and B12 (no escalate after
  `not_covered`) checks first, or to start turning `handoff/verification/` into a pytest suite.
- `code-review`: review the branch (`main..feat/linear-sales-flow`) before pushing or opening a PR.
- `anthropic-skills:xlsx`: optional. Fill the v2 xlsx Summary from the Rerun2 CSV (columns G, I,
  J, K).
- `claude-md-management:revise-claude-md`: update CLAUDE.md after the fixes.
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

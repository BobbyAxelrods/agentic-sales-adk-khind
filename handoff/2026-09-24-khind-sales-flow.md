# Handoff: KHIND sales flow. Next session: audit rerun 3 (Astra: 62/62), file it, push and open the PR

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions;
- `5be9410`: before rerun 3.

Rules, enforcement points, pitfalls and open issues are in `CLAUDE.md`; this file does not repeat
them. The code changes are in the commits listed below.

## Where things stand (2026-09-24, 12:05 MYT)

- **Branch** `feat/linear-sales-flow`, 9 commits ahead of `main` (`git log main..HEAD`). It is not
  pushed and there is no PR. `docs/` is the user's and stays untracked.
- **Code under test in rerun 3:** `04ec5c7`. The commits after it change only docs and
  `handoff/verification/`.
- **ADK Web** was restarted by the user at 11:04:29 MYT (pid 188682), so it serves `04ec5c7`.
- **Rerun 3 is done** (Astra in ADK Web, all 62 rows):
  - Astra's verdict: **62 Pass, 0 Fail**, 0 Blocked, 0 N/A.
  - The chats ran from 11:07:24 to 11:40:33 MYT (03:07:24Z to 03:40:33Z): 37 sessions in
    `apps/.adk/session.db`. Run A is session `dda91747`, first message "Hi".
  - Astra's bundle: `/mnt/c/Users/User/Documents/Codex/2026-09-24/files-mentioned-by-the-user-khind/outputs/`,
    the folder `KHIND_Smoke_Test_2026-09-24_Rerun3/` (report, results CSV, Evidence, Screenshots)
    and `KHIND_Smoke_Test_Evidence_2026-09-24_Rerun3.zip`.
  - Not audited yet and not copied to Obsidian yet.
- **`session.db` also holds 8 sessions of user `verify`** (02:12:52Z to 02:14:01Z). They are
  scripted E1 checks against the old code, before rerun 3. A start time of `03:05:00Z` leaves them
  out.
- **This session's work** (reasons in the commit messages and CLAUDE.md):
  - `d91a9ab`: the rerun-2 record;
  - `e1a3458`: fixes for B6, B12, D6 and E4. The coverage tool hands over itself, and text beside
    handoff calls is dropped;
  - `04ec5c7`: the PDPA guard, no media on a handoff turn, and the pick by search (E1);
  - `5be9410`: rerun 3 made the last test;
  - the rerun-2 audit: `Claude Audit of Astra Verdicts.md` in the Obsidian folder
    `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 2`. Use it as the template for rerun 3;
  - the verification log: `handoff/verification/rerun2_fix_run_2026-09-24.txt`.

## User decisions that bind the next session (2026-09-24)

- **Rerun 3 is the last test.** Record every failure or audit finding as an open issue, with
  evidence. Do not fix it and do not ask for another rerun.
- **Push `feat/linear-sales-flow` and open a PR to `main` after rerun 3, whatever the result.**
  The user approved this.
- A code review before the PR is optional. Its findings go into the PR description, not into fixes.

## Next session, in order

1. **Audit rerun 3** as for rerun 2:
   - `.venv/bin/python handoff/verification/extract_run.py 2026-09-24T03:05:00Z <scratchpad>/rerun3`
     (expect 37 sessions);
   - `.venv/bin/python handoff/verification/trace_run.py <scratchpad>/rerun3/run.json`: figures
     against the chunks, text beside tool calls, handoff turns with no text;
   - compare with Astra's `KHIND_Agent_Smoke_Test_Results_2026-09-24_Rerun3.csv` (columns G, I,
     J, K);
   - spot-check the rows whose contract changed today:
     - B2, B5-B7, B12: the handoff is in the `advance_purchase_stage` response, there is no escalate
       call, and B12 has no USP;
     - B6: no English text;
     - D6: "senarai" only with the list;
     - E1 and C2: the pick, maybe through `product_selected`;
     - E4: an emoji in every reply;
     - A8-A10 and F6: no personal data;
     - the first-pick replies.
2. **File it in Obsidian** (`/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`), as for rerun 2:
   - the folder `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 3/`, holding Astra's bundle,
     `Inputs/` and `Claude Audit of Astra Verdicts.md`;
   - `Inputs/` holds the 4 files of `handoff/smoke-test/` as of `04ec5c7`: the Astra prompt, the
     guide, and the v2 csv and xlsx;
   - the zip `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 3.zip`, a copy of Astra's evidence
     zip, next to the folder.
3. **Record the result** in the CLAUDE.md "Open issues" smoke-test bullet and "History", and in
   this file. Commit.
4. **Push and open the PR:**
   - `gh` is not installed, and git in WSL has no credential helper, so `git push` over HTTPS asks
     for credentials. Ask the user to run `git push -u origin feat/linear-sales-flow` in their own
     terminal, or to set up credentials first.
   - Open the PR at
     `https://github.com/BobbyAxelrods/agentic-sales-adk-khind/compare/main...feat/linear-sales-flow?expand=1`,
     or with `gh` once it is installed and logged in.
   - The PR description gives:
     - the linear flow;
     - the fix rounds;
     - the test results: 53/62, then 58/62, then rerun 3;
     - the open issues from CLAUDE.md;
     - the attribution lines that the next session's instructions require.

## Backlog not in CLAUDE.md

1. A missing-fact reply promises that an officer will confirm, but it hands nobody the chat (seen
   in D7 of rerun 2, for a discount request). Decide whether officers see these chats.
2. **Test gaps**, with no smoke-test row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

Everything else is in CLAUDE.md "Open issues":
- the Chatwoot webhook under ADK 1.31;
- the RAG corpus duplicates and prices;
- the `not-working` label;
- `escalated` never resets;
- the IC-photo step;
- the old docs;
- form-field re-listing;
- webhook Route A pending.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls and open issues.
- `git log main..HEAD`, and `git show e1a3458 04ec5c7` for this session's code.
- `handoff/verification/`:
  - `unit_checks.py` (158 checks) and `webhook_order.py` (7), both offline;
  - `scenarios.py`: 17 real-Gemini scenarios with 64 checks, run against `adk api_server` on port
    8001;
  - `extract_run.py` and `trace_run.py` for audits;
  - the run logs.
- `handoff/smoke-test/`:
  - the builder (`build_smoke_test_v2.py`);
  - the v2 csv and xlsx;
  - the guide;
  - `KHIND-Astra-ComputerUse-Prompt-v2.md`.

## Suggested skills

- `simple-english`: CLAUDE.md, this file and the Obsidian notes are written in short, plain
  English; keep that style.
- `code-review` (optional, before the PR, on `main..feat/linear-sales-flow`): note the findings in
  the PR; do not fix them.
- `claude-md-management:revise-claude-md`: update CLAUDE.md with the rerun-3 result.
- `anthropic-skills:xlsx` (optional): fill the v2 xlsx Summary from the rerun-3 CSV.
- `handoff`: write the next handoff into this same file.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, and
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`.
- ADK Web runs on port 8000. Run verification servers on port 8001 with
  `--session_service_uri memory://`. Follow the `pkill` rules in CLAUDE.md.
- `gh` is not installed; git in WSL has no credential helper.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

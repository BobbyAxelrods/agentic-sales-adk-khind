# Handoff: KHIND sales flow. Rerun 3 audited (62/62 confirmed). Next: push and open the PR

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions;
- `5be9410`: before rerun 3;
- `93691df`: rerun 3 done, before its audit.

Rules, enforcement points, pitfalls and open issues are in `CLAUDE.md`; this file does not repeat
them. The code changes are in the commits listed below.

## Where things stand (2026-09-24, 13:00 MYT)

- **Branch** `feat/linear-sales-flow`, 10 commits ahead of `main` (`git log main..HEAD`). It is
  not pushed and there is no PR. `docs/` is the user's and stays untracked.
- **Code under test in rerun 3:** `04ec5c7`. The commits after it change only docs and
  `handoff/`.
- **Rerun 3 is audited.** Astra's 62 of 62 Pass is confirmed; no verdict is overturned.
  - The audit read the 37 sessions of `apps/.adk/session.db` from 03:07:24Z to 03:40:33Z
    (84 user turns), with `extract_run.py`, `trace_run.py` and the new `check_run.py`.
  - Findings, now in CLAUDE.md "Open issues", not fixed:
    - G5's first attempt got a Vertex AI 502 and no retry (no `retry_options` on the model);
    - D2 got the missing-fact line although the DryMaster chunks list the promotion benefits;
    - C6 said "senarai produk kami" without showing the list;
    - the DryMaster warranty terms conflict (motor or compressor; 4 or 3 years on RTO).
- **Filed in Obsidian** (`/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/`):
  - the folder `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 3/`: Astra's bundle, `Inputs/`
    (the 4 files of `handoff/smoke-test/` as of `04ec5c7`) and `Claude Audit of Astra Verdicts.md`;
  - the zip `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 3.zip`, a byte copy of Astra's
    evidence zip.
- **Offline checks on `HEAD`:** `unit_checks.py` 158 of 158, `webhook_order.py` 7 of 7.
- **The PR description is ready:** `handoff/2026-09-24-pr-description.md` (body only). Title:
  `feat(flow): linear WhatsApp sales flow, smoke test 62 of 62`.
- The optional code review before the PR was not run.

## User decisions that bind the next session (2026-09-24)

- **Rerun 3 was the last test.** Its findings are recorded as open issues, with evidence. Do not
  fix them and do not ask for another rerun.
- **Push `feat/linear-sales-flow` and open a PR to `main`.** The user approved this.
- A code review before the PR is optional. Its findings go into the PR description, not into fixes.

## Next session, in order

1. **Push.** `gh` is not installed, and git in WSL has no credential helper, so `git push` over
   HTTPS asks for credentials. The user runs `git push -u origin feat/linear-sales-flow` in their
   own terminal, or sets up credentials first.
2. **Open the PR** to `main`:
   - in the browser:
     `https://github.com/BobbyAxelrods/agentic-sales-adk-khind/compare/main...feat/linear-sales-flow?expand=1`,
     with the title above and the body from `handoff/2026-09-24-pr-description.md`;
   - or, once `gh` is installed and logged in:
     `gh pr create --base main --head feat/linear-sales-flow --title "feat(flow): linear WhatsApp sales flow, smoke test 62 of 62" --body-file handoff/2026-09-24-pr-description.md`.
3. After the PR exists, record its URL here and in CLAUDE.md "History".

## Backlog not in CLAUDE.md

1. A missing-fact reply promises that an officer will confirm, but it hands nobody the chat (D7
   of rerun 2; D2 of rerun 3 is the same gap). Decide whether officers see these chats.
2. **Test gaps**, with no smoke-test row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

Everything else is in CLAUDE.md "Open issues":
- the Chatwoot webhook under ADK 1.31 (on `main` too);
- the rerun-3 findings (no model retry, D2, C6);
- the RAG corpus duplicates, and the DryMaster prices and warranty;
- the `not-working` label;
- `escalated` never resets;
- the IC-photo step;
- the old docs;
- form-field re-listing;
- webhook Route A pending.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls and open issues.
- `git log main..HEAD`, and `git show e1a3458 04ec5c7` for the last code changes.
- `handoff/verification/`:
  - `unit_checks.py` (158 checks) and `webhook_order.py` (7), both offline;
  - `scenarios.py`: 17 real-Gemini scenarios with 64 checks, run against `adk api_server` on port
    8001;
  - `extract_run.py`, `trace_run.py` and `check_run.py` for audits of an ADK Web run;
  - the run logs.
- `handoff/smoke-test/`:
  - the builder (`build_smoke_test_v2.py`);
  - the v2 csv and xlsx;
  - the guide;
  - `KHIND-Astra-ComputerUse-Prompt-v2.md`.
- The Obsidian audit notes of rerun 2 and rerun 3 (`Claude Audit of Astra Verdicts.md`).

## Suggested skills

- `simple-english`: CLAUDE.md, this file and the Obsidian notes are written in short, plain
  English; keep that style.
- `code-review` (optional, before the PR, on `main..feat/linear-sales-flow`): note the findings in
  the PR; do not fix them.
- `handoff`: write the next handoff into this same file.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, and
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`.
- ADK Web runs on port 8000 (started by the user). Run verification servers on port 8001 with
  `--session_service_uri memory://`. Follow the `pkill` rules in CLAUDE.md.
- `gh` is not installed; git in WSL has no credential helper.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

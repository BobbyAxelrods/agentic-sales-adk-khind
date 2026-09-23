# Handoff: KHIND sales flow (2026-09-24). Next session: Astra rerun of the fixed flow, then audit

The first version of this handoff (the v2 run results and the fix hypotheses) is in commit `cc153b1`.

## Where things stand

- **The v2 smoke test** (Astra in ADK Web, 2026-09-24) passed 53 of 62 rows on commit `cc153b1`,
  branch `feat/linear-sales-flow`.
  - Claude audited all 83 turns from `apps/.adk/session.db`. The audit confirmed every failure
    and overturned no pass.
  - The audit record is `Claude Audit of Astra Verdicts.md` in the Obsidian folder
    `/mnt/d/Obsidian_folder/Personal/Personal/Khind Test/2026-09-24 - KHIND Linear Flow Smoke Test/`.
    That folder also holds Astra's bundle, a copy of the zip, and the v2 test inputs.
- **The fixes for the 9 failing rows are committed** on the same branch, in the commit after
  `cc153b1`. Verification (`handoff/verification/fix_run_2026-09-24.txt`):

  | Check | Result |
  |---|---|
  | `unit_checks.py`, offline | 118 of 118 |
  | `webhook_order.py` | 7 of 7 |
  | `scenarios.py`, real Gemini: 15 scenarios, one per failing row plus the old ones | 49 of 49, twice |

- **Not done yet:** the full 62-row Astra rerun against the regenerated v2 sheet.
- **ADK Web** (`adk web --port 8000 .`, pid 138908) still runs the OLD agent: it caches the agent,
  and it started before the fixes. It must be restarted before the rerun. It is the user's
  process, so ask first.

## Decisions by the user (2026-09-24)

1. Commit the tested code on `feat/linear-sales-flow`. Done.
2. Keep the test record in the Obsidian folder above. Done.
3. Employment rules are confirmed: a pensioner is not working (handoff); self-employed, a
   business owner, gig and part-time work count as working (RM1 line).
4. A fact missing from the documents is not a handoff. The agent sends `KB_GAP_LINE`, then the
   pending question. `rag-error` is only for a failed retrieval (tool status `error`).
5. The coverage verdict moves into code. A Peninsular state alone counts as covered.
6. Wording of the new fixed lines, approved:
   - `KB_GAP_LINE`: "Maaf, maklumat [topik] belum ada dalam sistem saya. Pegawai kami akan sahkan
     dengan cik/tuan nanti ya 🙏"
   - `APPLICATION_COMPLETE_LINE`: "Terima kasih, butiran permohonan cik/tuan sudah lengkap! 👍 Boleh
     hantar *gambar IC depan & belakang* sekarang?"
7. The rerun covers all 62 rows.

## What the fix commit changed

| Row | Confirmed cause | Fix |
|---|---|---|
| A3 | Top-3 search over the whole corpus returned the Lite 480L price table. The 592L document holds RM99 and RM119 a month over 60 months. | `rag_tool`: search only the file of the product named in the query, else the active product (`top_k=8`, the whole document). |
| G6 | No product switch on "balik pada 592L tadi". The same retrieval miss hid the weight (85 kg), then came a `rag-error` handoff. | A core rule: switch first. Scoped search. `KB_GAP_LINE` instead of a handoff. |
| B10 | The model judged "96800" alone as covered. | `apps/services/coverage.py` decides. `advance_purchase_stage(postcode, town, state)` returns `ok`, `not_covered`, `need_town`, `need_state` or `need_location`. |
| B11 | The reply rule and the coverage fragment said "reply ONLY with the location question", although the message held an area. | A stage-aware `reply_rule`: check a place given in the same message. |
| C2 | "Ada aircond tak?" read as browsing. | The discovery fragment checks for a single product first; the pending step says "call set_product_interest instead of asking". |
| D4 | No grouped list in the prompt at the location stage. | `PRODUCT_MENU` in the core prompt, copied exactly. |
| D5 | The model followed its own "which product?" from D4. | A `Pending step` line in Current State; every reply ends with that question. |
| D6 | "KHIND tidak menjual microwave" (false for the brand). | A rule: this scheme covers only the 8 products. |
| E4 | Replies after the form was complete ended with a request, not a question. | Fixed `APPLICATION_COMPLETE_LINE`. The pending step asks for the IC photos. |

Found and fixed during this work:

- **The model's own comments after a first pick.** The model added praise or invented claims after
  almost every first pick, whatever the prompt said: 0 of 15 clean replies. One was "Penjimatan
  tenaga elektrik sehingga 50%".
  - `insert_pending_usp` now keeps only the question on a plain pick: the fixed location question
    at the location step, otherwise the model's closing question.
  - A pick is not plain when `query_product_info` or `advance_purchase_stage` ran in the same
    turn. Both tools mark the turn with `reply_facts_invocation`.
- **`vrag.list_files` failed in the server.** It goes to us-central1, because the vertexai SDK
  ignores `GOOGLE_CLOUD_LOCATION`. `rag_tool` now calls `vertexai.init` with the corpus's region.
- **The escalation tool crashed.** `dict(tool_context.state)` raises `KeyError: 0`, so every real
  Chatwoot escalation would have crashed. It now uses `to_dict()`.
- **Two guards:**
  - Text written beside an `advance_purchase_stage` call is dropped.
  - A turn that escalates gets no USP, so the fixed handoff line can apply.
- **`customer_location` is now written.** The Chatwoot handoff note reads it.

## Activities for the next session, in order

1. **Ask the user to restart ADK Web,** or do it with their OK:
   `pkill -f "[a]dk web"`, then `.venv/bin/adk web --port 8000 .` from the repo root. Run these
   as two separate commands (see CLAUDE.md).
2. **The user runs Astra** on all 62 rows:
   - the prompt is `handoff/smoke-test/KHIND-Astra-ComputerUse-Prompt-v2.md`, unchanged;
   - the sheet is the regenerated `KHIND_Agent_Smoke_Test_Prompts_v2.csv` and `.xlsx`, whose
     expectations now match the fixes (A3, A10, A11, B rows, D4, D6, E1, F6, F9, F10, G6 and the
     Reference sheet);
   - column L still holds the 2026-09-20 result.
3. **Audit the rerun** as before:
   - `.venv/bin/python handoff/verification/extract_run.py <run start, UTC> <out_dir>`;
   - read `transcripts.txt` against the results CSV;
   - trace every figure to the chunk `source` (now also `scope` and `products`);
   - compare each row with the 2026-09-24 result (`KHIND_Agent_Smoke_Test_Results_2026-09-24.csv`
     in the Obsidian folder).
4. **Update** CLAUDE.md "Open issues", this file, and the Obsidian record: add the rerun bundle and
   an audit note.

## Backlog

1. **Session layer.** Fix `apps/runner.py` so the Chatwoot webhook runs (defects in CLAUDE.md).
   Then test on a real phone:
   - media before text;
   - handoff lines delivered, labels applied, and the handoff note showing `customer_location`;
   - no double product list (the catalog message plus the model's list).
2. **Ops.** Create the `not-working` label in Chatwoot.
3. **Corpus**, for the user or KHIND:
   - delete the older duplicates of `khind_acson_knowledge_base.md` and
     `khind_dhp90_drymaster_heatpump_dryer_knowledge_base.md` (2026-09-12 03:15Z and 03:32Z);
   - confirm which of the two DryMaster price tables is current;
   - add the aircond monthly price if one exists.
4. **IC photos.** `webhook.py` drops messages that hold only images, so the IC-photo step never
   ends. Decide what happens after the photos: an officer handoff, or a note.
5. **Housekeeping.** `KHIND_MASTERPROMPT.md` and `TASK_TRACKER.md` still describe the old flow.
6. **Test gaps.** No row covers:
   - a product question after the RM1 invite, or while the form is being filled;
   - a customer who declines the eligibility check;
   - a comparison between two products (the search now covers both documents);
   - a question with no product at discovery (it still searches the whole corpus).

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls, and open issues.
- `handoff/verification/`:
  - `unit_checks.py`, `webhook_order.py` and `scenarios.py` (use `KHIND_API_BASE`, port 8001);
  - `extract_run.py`;
  - `fix_run_2026-09-24.txt`.
- `handoff/smoke-test/build_smoke_test_v2.py`: regenerates the sheet from `apps/prompts/khind_prompts.py`
  with `uv run --no-project --with openpyxl python handoff/smoke-test/build_smoke_test_v2.py`.
- The approved plan for this fix round: `/home/risdin/.claude/plans/witty-tumbling-ladybug.md`.
- Earlier plans: `/home/risdin/.claude/plans/continue-plan-from-home-risdin-claude-pl-breezy-wolf.md`
  and `/home/risdin/.claude/plans/based-on-the-current-cheerful-wolf.md`.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, model
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`. LibreOffice is
  not installed.
- Stop dev servers with `pkill -f "[a]dk web"` or `pkill -f "[a]dk api_server"`. Never put the
  pkill and the restart in the same command.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

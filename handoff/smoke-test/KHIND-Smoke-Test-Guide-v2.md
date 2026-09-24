---
title: KHIND Sales Agent - Smoke Test Guide v2 (linear flow)
date: 2026-09-24
app: agentic-sales-adk-khind
runner: adk web (app "apps")
supersedes: KHIND-Smoke-Test-Guide.md (2026-09-20)
---

# KHIND Sales Agent - Smoke Test Guide v2

Companion note for `KHIND_Agent_Smoke_Test_Prompts_v2.xlsx`: 62 cases on 3 sheets, **Smoke Test**,
**Reference** and **Summary**. It tests the linear sales flow introduced on 2026-09-24: product,
then postcode and area, then "kerja atau tidak", then the RM1 promo, then the form. The agent under
test runs on Gemini 2.5 Flash with a thinking budget of 1024 tokens.

## Files

| File | Use |
|---|---|
| `KHIND_Agent_Smoke_Test_Prompts_v2.xlsx` | The test sheet. Fill the yellow columns G, I, J, K. Column L holds the 2026-09-20 result. |
| `KHIND_Agent_Smoke_Test_Prompts_v2.csv` | Flat copy, UTF-8. Upload this to the computer-use agent. |
| `KHIND-Astra-ComputerUse-Prompt-v2.md` | Paste-ready prompt that makes Astra run the whole suite in the browser. |
| `KHIND-Smoke-Test-Guide-v2.md` | This note. |
| `build_smoke_test_v2.py` | Regenerates the xlsx and csv. It reads the fixed texts from `apps/prompts/khind_prompts.py`, so edit the rows there and rerun instead of editing the sheet by hand. |

Regenerate from the repo root:

```bash
uv run --no-project --with openpyxl python handoff/smoke-test/build_smoke_test_v2.py
```

## How to run by hand

1. From the repo root: `.venv/bin/adk web --port 8000 .`, then open http://localhost:8000.
2. In "Select an agent" choose **apps**. Replies are authored by `khind_sales_agent`.
3. Start a **New Session** whenever column C says so, and send the warm-up it names.
   W1 is "1". W2 is "1" followed by "Poskod 43000, Kajang Selangor".
4. Paste column D into the chat box and compare the reply with column E.
5. Check the tool calls in **Events** against column F and the **State** tab against column H.
6. Fill G, I, J and K. The Summary sheet totals the results and compares them with 2026-09-20.

## What will NOT happen in ADK Web (not a bug)

| Feature | Why |
|---|---|
| Product photos and video | Media is sent by `apps/webhook.py` through GCS and Chatwoot. `set_product_interest` still returns `media_delivery: "trigger"`. |
| USP text in the tool response | By design the tool returns `usp_sent_automatically: true`. Code inserts the approved USP into the reply. |
| WhatsApp button list | Sent by the webhook. ADK Web shows the numbered 1-8 text list instead. |
| Chatwoot handoff | Without a Chatwoot conversation ID the handoff returns `chatwoot: "skipped"` but still sets `escalated: true`. For an area that is not covered, `advance_purchase_stage` makes the handoff itself. |
| One handoff line | Code removes text written with a coverage or handoff call, so ADK Web and production both show one handoff line, written after the tool. |
| Vertex session persistence and the webhook | ADK Web uses its own runner and session service. The webhook path is a separate, known issue (see `CLAUDE.md`). |

## Coverage of the smoke test

| Run | Rows | Covers |
|---|---|---|
| 0 | P1-P2 | App loads as `apps`; 6 tools declared |
| A | A1-A11 | Full happy path in one session: list, pick with exact USP, price question, linear rule, coverage, kerja, RM1, form, field capture, duplicate-form guard |
| B | B1-B12 | Coverage lists, the not-covered handoff line, unclear areas, product and area in one message |
| C | C1-C8 | Pick by number, keyword, model code, Malay alias, invalid input, webhook token, repeat mention |
| D | D1-D7 | Product Q&A at the location step: product-identity of figures, list resend, out-of-catalogue, discount pressure |
| E | E1-E4 | Bahasa Melayu for English and Chinese input, shorthand, style audit |
| F | F1-F11 | Handoff labels (human, angry, not working), who counts as working, prompt injection, role change, PDPA readback, no selling after handoff |
| G | G1-G7 | Product recall, session reset, emoji and garbage input, product switch at the kerja and location steps |

## What to watch

- **Rerun 2 failures (2026-09-24, fixed after it).**
  - B6 and B12: the coverage handoff is now made by `advance_purchase_stage` itself. Check its
    Function Response (`escalated: true` and the label) and State, and that the reply is only the
    not-covered line, with no USP and no English text.
  - D6: "senarai" only when the list is shown.
  - E4: every reply needs an emoji; bold is only for key terms.
- **Figures from the wrong product (A3, G6).** Searches are limited to the product's own document
  (Function Response: scope `product`). Quoting RM75/RM95 or 80kg/87kg for the 592L is still a
  Critical fail. The Reference sheet maps every product to its source document.
- **PDPA (A8).** A name echo such as "Terima kasih Ali bin Abu" was seen on 2026-09-20 and again
  on 2026-09-24, also in scripted form-step runs after rerun 2.
- **Duplicate blank form (A11).** It happened on 2026-09-20.
- **USP exactly once (A2, B1, C1-C7, G5, G7).** Count the ✅ lines against the Reference sheet. An
  extra block means the model wrote its own description and the code guard missed it.
- **Never a payslip question, never RM0.** Both belong to the old flow.
- **Employment rules (F9, F10).** Confirmed on 2026-09-24: pensioner = not working,
  self-employed = working.

## Quick copy-paste prompts (happy path, one session)

```
Hi
1
Berapa harga ansuran bulanan untuk model ni?
Ok saya berminat, macam mana nak apply?
Poskod 43000, Kajang Selangor
Ya saya kerja swasta
Ok jom semak
Nama Ali bin Abu, No IC 900101015511, WhatsApp 0123456789
Emel saya ali@gmail.com, alamat No 5 Jalan Bunga, Kajang. Kerja sebagai teknisi di Syarikat ABC Sdn Bhd mula Jan 2020
Kecemasan: Siti binti Ahmad, 0198887777, isteri
Boleh hantar borang sekali lagi?
```

The identity data above is the same fictional test data as in the 2026-09-20 run.

## Automated run (Astra computer use)

1. Start `adk web` as above and select **apps**.
2. Open Astra in computer-use mode on that tab.
3. Upload `KHIND_Agent_Smoke_Test_Prompts_v2.csv`.
4. Paste the block from `KHIND-Astra-ComputerUse-Prompt-v2.md`.

Astra runs all 62 rows in ID order, keeps Run A in one session, reads tool calls from **Events**
and state from **State**, and returns the filled results, a failure table with severity, a
comparison with 2026-09-20 and with rerun 2, screenshots and an evidence bundle.

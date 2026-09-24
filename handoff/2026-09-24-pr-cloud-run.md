## Summary

The Chatwoot webhook app can now run on Cloud Run. Before this PR it failed on every message
under ADK 1.31, answered any payload with text in it, and trusted any caller. It now accepts only
calls that Chatwoot signed, answers only customer messages in chats the bot owns, returns 200 at
once, and keeps sessions in a Vertex AI Agent Engine. Nothing is deployed yet: the GCP setup and
the staging deploy come next, after approval.

Base: `main` after the linear-flow PR (`feat/linear-sales-flow`) is merged.

## Why the webhook works this way

From the Chatwoot v4.18.0 source (Chatwoot Cloud runs 4.18.0):

- Chatwoot waits 5 s for the webhook response. A slower or failed response opens the pending chat
  for officers ("marked open by system due to an error with the agent bot"). Our turns take
  4-10 s, so the old code set every chat back to pending after each reply.
- The agent bot receives every message event of its inbox: its own replies, officers' replies,
  private notes and WhatsApp delivered/read updates. It still receives them after a handoff.
- Agent-bot calls are signed: `X-Chatwoot-Signature` is HMAC-SHA256 of `"<timestamp>.<body>"`
  with the bot's Webhook Secret.
- Messages sent with the bot's token never change the chat status.
- `POST .../labels` replaces all of a chat's labels.

## Changes

- `apps/webhook.py`
  - Checks the signature (401 when it is missing or wrong, when the timestamp is more than 5
    minutes off, or when no secret is set).
  - Answers only `message_created`, `incoming`, not private, in a `pending` chat. Repeated message
    IDs are skipped.
  - Returns 200 at once. The turn runs in the background, one at a time per chat, in order.
  - Media first (the text waits at most 20 s), then the text. No pending toggles.
  - A chat that is pending again after a handoff resumes the flow, after a live status check.
  - Photos after a complete application: a handoff (`human-required`) and a fixed line
    (`IC_PHOTOS_RECEIVED_LINE`, new text that still needs approval).
  - No product menu of its own: the model's greeting already holds `PRODUCT_MENU`, so the customer
    got the list twice. Route A (list-reply row IDs) is removed: Chatwoot drops the row ID.
- `apps/runner.py`: the Runner on the durable store, awaited, with no per-instance cache. It uses
  Agent Engine sessions (`VERTEX_AI_AGENT_ENGINE_ID`, now read) or memory when that is unset. The
  session ID is `conv-<id>`, because Agent Engine allows only `[a-z0-9-]`. State outside a turn is
  an event with a state delta.
- `apps/clients/chatwoot.py`: the handoff label is added to the existing labels, failed handoff
  steps are logged, and `get_conversation_status` reads the live status.
- `apps/agent.py`: `Gemini(retry_options=...)`, 3 attempts on 408, 429 and 5xx (G5 of rerun 3).
- `apps/config.py`: reads `VERTEX_AI_AGENT_ENGINE_ID` and `CHATWOOT_WEBHOOK_SECRET`, and strips
  whitespace around values.
- Container: `Dockerfile` (python:3.12-slim, non-root), `.dockerignore`, and `.gcloudignore` as an
  allow list (no `.env`, key file or session database is uploaded). `constraints.txt` pins all
  119 packages to the tested versions. At shutdown the app waits up to 8 s for running turns.

## User decisions (2026-09-24)

- Stay in the current GCP project.
- Sessions go in a new Agent Engine, `khind-sales-sessions` (created).
- Staging uses a separate test inbox.
- A chat that comes back to the bot resumes the flow.

## Checks

| Script (`handoff/verification/`) | Kind | Result |
|---|---|---|
| `unit_checks.py` | offline | 158 of 158 |
| `session_checks.py` | offline, stub agent | 13 of 13 |
| `webhook_checks.py` | offline, ASGI | 43 of 43; all 11 deliberate code breaks caught |
| `session_online.py` | real Agent Engine and Gemini | 8 of 8 |
| `replay_local.py` | end to end: the app and a mock Chatwoot on local ports | 10 of 10 |

- The Docker daemon does not run in WSL, so the image steps were run by hand instead. A clean
  Python 3.12 env was built from `requirements.txt` and `constraints.txt`, with `pip check` clean.
  The app then ran from a folder with only `apps/` and environment variables.
- There is no WhatsApp test yet: that is the staging step.

## Next (not in this PR)

1. GCP setup, after approval: a runtime service account with no key, its roles, and the staging
   secrets in Secret Manager.
2. A test inbox with its own agent bot, then the staging deploy (`--min-instances 1
   --max-instances 1 --no-cpu-throttling`) and a WhatsApp smoke test.
3. Production, then alerts.

The steps and commands are in `handoff/2026-09-24-khind-sales-flow.md`.

## Open issues

- One instance only: the per-chat turn lock is in process memory (`--max-instances 1`).
- Sessions never expire. They hold names, IC and phone numbers, so a retention time is needed.
- Voice notes, files and images before the form is complete get no reply.
- `query_product_info` caches its results in session state, which grows with each new question.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01XfM8uvzMzF6on23ZPaqkr6

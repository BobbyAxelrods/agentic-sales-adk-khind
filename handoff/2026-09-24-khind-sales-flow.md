# Handoff: KHIND sales flow. Next: push and open the PR, then publish to Cloud Run

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions;
- `5be9410`: before rerun 3;
- `93691df`: rerun 3 done, before its audit;
- `2e4d1a6`: rerun 3 audited, before the Cloud Run plan.

Rules, enforcement points, pitfalls and open issues are in `CLAUDE.md`; this file does not repeat
them. The code changes are in the commits listed below.

## Where things stand (2026-09-24, 18:10 MYT)

- **Branch** `feat/linear-sales-flow` at `2e4d1a6`, 10 commits ahead of `main`. It is **not
  pushed**: the remote has only `main`. There is no PR. `docs/` is the user's and stays untracked.
- **The GitHub repo looks public:** `git ls-remote` works with no credentials. Keep secrets,
  customer data and personal paths out of new commits, deploy files and the PR.
- **Rerun 3 is audited.** Astra's 62 of 62 is confirmed. The findings are in CLAUDE.md "Open
  issues" and are not fixed. The audit note is in the Obsidian folder
  `2026-09-24 - KHIND Linear Flow Smoke Test - Rerun 3`.
- **Shared test report:** the doc "KHIND Agent Smoke Test Report: Rerun 3"
  (`https://claude.ai/artifact/3sXrGyfVs2kE1GWw64jYeA`):
  - the "Report" tab holds the findings and the results of all 62 cases;
  - the "Actual outputs" tab holds each case's prompt, tool calls and exact reply. All 59 replies
    were checked by SHA-256 against `session.db`.

  It is private until the user shares it. To edit it, use the Claude Docs connector, not a
  publish.
- **The PR description is ready:** `handoff/2026-09-24-pr-description.md` (body only). Title:
  `feat(flow): linear WhatsApp sales flow, smoke test 62 of 62`.
- **Offline checks on `2e4d1a6`:** `unit_checks.py` 158 of 158, `webhook_order.py` 7 of 7.
- **Cloud Run:** nothing is deployed for KHIND, and the repo has no Dockerfile or deploy config.
  - `gcloud` is logged in to project `prudential-poc-484904` with no default region. `docker` is
    installed.
  - The project has one unrelated Cloud Run service (asia-southeast1). Do not touch it.

## User decisions that bind the next session (2026-09-24)

- **Rerun 3 was the last smoke test.** Its findings are open issues, not fixes in this PR.
- **Push `feat/linear-sales-flow` and open a PR to `main`.** The user approved this.
- A code review before the PR is optional. Its findings go into the PR description, not into fixes.
- **Next focus: publish the agent to Cloud Run**, with the plan below. The user has not yet
  answered the plan's decisions, and has not approved any deploy or any change to GCP resources.

## Next session, in order

1. **Push and open the PR** (still to do):
   - `gh` is not installed and git in WSL has no credential helper. The user runs
     `git push -u origin feat/linear-sales-flow` in their own terminal.
   - Open the PR in the browser:
     `https://github.com/BobbyAxelrods/agentic-sales-adk-khind/compare/main...feat/linear-sales-flow?expand=1`,
     with the title above and the body from `handoff/2026-09-24-pr-description.md`.
   - Record the PR URL here and in CLAUDE.md "History".
2. **Ask the user the Cloud Run decisions** (D1 to D4 below).
3. **Work through the Cloud Run plan**, phase by phase. Do the code on a new branch, for example
   `feat/cloud-run`, based on `feat/linear-sales-flow` or on `main` after the merge.

## Plan: publish the agent to Cloud Run

The target is the Chatwoot webhook app (`apps/main.py`, FastAPI, `POST /webhook`). Chatwoot calls
it for each WhatsApp message, and it replies through the Chatwoot API. ADK Web is a test UI only:
never deploy it in public. `adk deploy cloud_run` deploys the ADK dev server, not this app.

### What the code already has, and what blocks a deploy

- Ready: `GET /health`; the port comes from `PORT`; the GCS, Vertex AI and RAG clients use
  Application Default Credentials; Chatwoot calls have timeouts and retries.
- Blockers found on 2026-09-24:
  - **Sessions (open issue in CLAUDE.md).** `apps/runner.py` never awaits the coroutines of the
    async session methods, in memory and on Vertex AI (some run inside `asyncio.to_thread`). It
    never passes `agent_engine_id` (`VERTEX_AI_AGENT_ENGINE_ID` is never read), and it patches a
    copy of the session. It also keeps a per-instance in-memory cache (`_memory`, `_loaded`) that
    goes stale when Cloud Run runs more than one instance.
  - **No event filter.** `POST /webhook` acts on any payload that holds text. It does not check
    `event`, `message_type` or `private`. So the bot's own replies, an officer's replies and
    status events can be treated as customer text: `_extract_inbound_text` also reads text under
    `messages`, where conversation events can carry the last message.
  - **No caller check.** `CHATWOOT_WEBHOOK_SECRET` is in `.env` but no code reads it. A public
    URL would let anyone trigger model calls and Chatwoot sends.
  - **Long synchronous request.** The handler runs the whole turn before it returns 200: the
    model, up to 20 s of media, then the Chatwoot sends. Chatwoot's webhook timeout and retry
    behaviour are not known yet.
  - **Work after the response.** Late media uploads, the second `set_conversation_pending` and
    the Vertex AI session flush run as background tasks. With request-based billing, Cloud Run
    throttles the CPU after the response, so they can stall.

### Decisions for the user (ask first)

- **D1. GCP project.** Stay in `prudential-poc-484904`, where the RAG corpus, bucket
  `khind_2028` and Vertex AI already are? Or use a new KHIND project, where the corpus and the
  media must be set up again?
- **D2. Session store.** Recommended: Vertex AI Agent Engine sessions (`VertexAiSessionService`
  with `agent_engine_id`), which is what the code meant to use. It needs an Agent Engine resource:
  check whether the one named in `.env` exists. Other option: Cloud SQL (Postgres) with
  `DatabaseSessionService`.
- **D3. Webhook authentication.** Recommended: a secret token in the webhook URL that Chatwoot
  calls, checked in constant time. Use Chatwoot's signature header instead if the installed
  Chatwoot version sends one. Cloud Run IAM cannot be used, because Chatwoot cannot send Google
  identity tokens.
- **D4. Staging.** Is there a test Chatwoot inbox and WhatsApp number for a staging service?

### Phase 1: make the webhook path work (code, before any deploy)

1. Rewrite the session layer in `apps/runner.py`:
   - run the Runner directly on the durable store (D2), awaited;
   - remove `_memory`, `_loaded` and the background flush;
   - change state outside a run with `append_event` and `EventActions(state_delta=...)`, not by
     editing a copy.

   Then more than one instance is safe. This fixes the CLAUDE.md open issue.
2. In `apps/webhook.py`, act only on `event == "message_created"` with
   `message_type == "incoming"` and not `private`, and ignore everything else. Also skip repeats
   by Chatwoot message id, in case Chatwoot retries.
3. Check the caller (D3) and return 401 or 403 before any work.
4. Find Chatwoot's webhook timeout and retry behaviour. If a turn can outlast it, return 200 first
   and run the turn in the background (this needs CPU always allocated), or queue it with Cloud
   Tasks.
5. Add a model retry: `Gemini(model=..., retry_options=types.HttpRetryOptions(...))` in
   `apps/agent.py`. This is the rerun-3 G5 finding.
6. Fix the open issues that customers would hit on WhatsApp:
   - Route A sets pending after a handoff;
   - the IC-photo step drops image-only messages, so the customer gets no reply and no officer is
     told. At least hand over to an officer when an image arrives after the form.
7. Add `tenacity` to `requirements.txt`. `apps/clients/chatwoot.py` imports it, but today it comes
   in only through `google-adk` and `google-genai`.
8. Checks:
   - add offline checks for the event filter, the caller check and the session layer, next to
     `handoff/verification/unit_checks.py` and `webhook_order.py`;
   - run `uvicorn apps.main:app` locally and replay saved Chatwoot payloads with `curl`;
   - test once against a test Chatwoot inbox.

### Phase 2: container and GCP setup (ask before creating resources)

1. Add a `Dockerfile` and a `.dockerignore` (or `.gcloudignore`):
   - `python:3.12-slim`, `pip install -r requirements.txt`, and copy `apps/` only;
   - `CMD exec uvicorn apps.main:app --host 0.0.0.0 --port ${PORT:-8080}`;
   - exclude `.env`, `*.json`, `.venv/`, `.adk/`, `graphify-out/`, `docs/` and `handoff/`.

   Never put the service-account key or `.env` in the image or the repo.
2. Enable the APIs if they are off: Cloud Run, Cloud Build, Artifact Registry, Secret Manager
   (Vertex AI and Storage are already in use).
3. Create a runtime service account and use no JSON key. Its roles:
   - `roles/aiplatform.user`: Gemini, RAG and Agent Engine sessions;
   - `roles/storage.objectViewer` on bucket `khind_2028`: media listing and download;
   - `roles/secretmanager.secretAccessor` on the two secrets below.
4. Put `CHATWOOT_API_TOKEN` and `CHATWOOT_WEBHOOK_SECRET` in Secret Manager.
5. Set these plain environment variables:
   - `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_PROJECT`,
     `GOOGLE_CLOUD_LOCATION=asia-southeast1` and `LLM_MODEL`;
   - `RAG_CORPUS_NAME`, `GCS_BUCKET` and `VERTEX_AI_AGENT_ENGINE_ID`;
   - `CHATWOOT_BASE_URL`, `CHATWOOT_ACCOUNT_ID` and `CHATWOOT_HUMAN_AGENT_ID`.

   Do not set `GOOGLE_APPLICATION_CREDENTIALS` or `PORT`.

### Phase 3: deploy, staging first

1. Deploy the staging service:

   ```
   gcloud run deploy khind-sales-agent-staging --source . --region asia-southeast1 \
     --service-account <runtime SA> --allow-unauthenticated \
     --min-instances 1 --timeout 120 --no-cpu-throttling \
     --set-env-vars <the variables above> \
     --set-secrets CHATWOOT_API_TOKEN=<secret>:latest,CHATWOOT_WEBHOOK_SECRET=<secret>:latest
   ```

   - `--allow-unauthenticated` is needed because Chatwoot cannot authenticate to Google. The
     webhook secret is the guard.
   - `--min-instances 1` avoids a cold start on the first message.
   - `--no-cpu-throttling` lets the background media uploads finish.
   - Until Phase 1 step 1 is done, also set `--max-instances 1`.
2. Point the test inbox's bot or webhook at `https://<service URL>/webhook` with the secret.
3. Run a smoke test on WhatsApp:
   - the happy path (A1 to A11);
   - a list pick (Route A) and the media order: 2 images and 1 video, then the text;
   - an uncovered area (B2), not working (F3), a request for a human (F1) and a product question
     (D1);
   - the Chatwoot labels and the pending/open status after each handoff;
   - no replies to the bot's own messages;
   - Cloud Logging: no errors, and no "ADK runner failed".
4. Production:
   - deploy `khind-sales-agent` from the same source;
   - check it the same way, then switch the production inbox's bot URL;
   - rollback: point Chatwoot back, or run
     `gcloud run services update-traffic khind-sales-agent --to-revisions <previous>=100`.

### Phase 4: operate

- Alerts on the 5xx rate and on "ADK runner failed" log lines (customers then got the
  technical-problem line).
- A budget alert for Vertex AI spend.
- Optional: a Cloud Build trigger on `main`, and a private (`--no-allow-unauthenticated`)
  `adk api_server` service to run `scenarios.py` or Astra smoke tests against the cloud.

### Before go-live, outside the code (KHIND or the team)

- Create the `not-working` label in Chatwoot.
- KHIND confirms the DryMaster price and warranty terms and gives the aircond monthly price.
- Delete the older duplicate corpus files (see CLAUDE.md "RAG corpus data").

## Backlog not in CLAUDE.md

1. A missing-fact reply promises that an officer will confirm, but it hands nobody the chat (D7
   of rerun 2; D2 of rerun 3 is the same gap). Decide whether officers see these chats.
2. **Test gaps**, with no smoke-test row for:
   - a product question after the RM1 invite or during the form;
   - a customer who declines the eligibility check;
   - a comparison between two products;
   - a question with no product at discovery.

Everything else is in CLAUDE.md "Open issues".

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls and open issues.
- `git log main..HEAD`, and `git show e1a3458 04ec5c7` for the last code changes.
- For the Cloud Run work: `apps/main.py`, `apps/config.py`, `apps/runner.py`, `apps/webhook.py`,
  `apps/clients/chatwoot.py`, `apps/clients/gcs.py` and `requirements.txt`.
- `handoff/verification/`:
  - `unit_checks.py` (158 checks) and `webhook_order.py` (7), both offline;
  - `scenarios.py`: 17 real-Gemini scenarios with 64 checks, run against `adk api_server` on port
    8001;
  - `extract_run.py`, `trace_run.py` and `check_run.py` for audits of an ADK Web run;
  - the run logs.
- `handoff/smoke-test/`: the builder, the v2 csv and xlsx, the guide and the Astra prompt.
- The Obsidian audit notes of rerun 2 and rerun 3 (`Claude Audit of Astra Verdicts.md`), and the
  shared test report above.

## Suggested skills

- `simple-english`: CLAUDE.md, this file and the Obsidian notes are written in short, plain
  English; keep that style.
- `code-review` (optional, before the PR, on `main..feat/linear-sales-flow`): note the findings in
  the PR; do not fix them.
- `diagnose`: for the session layer under ADK 1.31 (Phase 1 step 1).
- `tdd`: for the Phase 1 fixes. Write the offline checks first.
- `run`: to start the FastAPI app locally and replay Chatwoot payloads.
- `security-review`: before the service gets a public URL (the caller check, the secrets, and
  the files that go into the image).
- `handoff`: write the next handoff into this same file.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0` pinned, and
  `gemini-2.5-flash` with a thinking budget of 1024.
- `openpyxl` is not in `.venv`; use `uv run --no-project --with openpyxl ...`.
- ADK Web runs on port 8000 (started by the user). Run verification servers on port 8001 with
  `--session_service_uri memory://`. Follow the `pkill` rules in CLAUDE.md.
- `gh` is not installed; git in WSL has no credential helper. `gcloud` and `docker` are installed.
- Secrets live in the git-ignored `.env` and service-account JSON. Never print or copy them. The
  test prompts use fictional identity data only.

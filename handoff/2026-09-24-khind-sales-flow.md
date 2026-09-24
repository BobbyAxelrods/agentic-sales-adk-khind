# Handoff: KHIND sales agent. Next: GCP setup and the staging deploy on Cloud Run

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions;
- `5be9410`: before rerun 3;
- `93691df`: rerun 3 done, before its audit;
- `2e4d1a6`: rerun 3 audited, before the Cloud Run plan;
- `e56ebb6`: the Cloud Run plan, before Phase 1.

Rules, enforcement points, pitfalls and open issues are in `CLAUDE.md`; this file does not repeat
them.

## Where things stand (2026-09-24, 19:20 MYT)

- **Branches** (nothing is pushed yet; the remote has only `main`):
  - `feat/linear-sales-flow` at `e56ebb6`, 11 commits ahead of `main`: the linear flow and the
    smoke tests. Its PR is ready (see "Next steps", step 1).
  - `feat/cloud-run`, based on `feat/linear-sales-flow`: the Cloud Run work below.
  - `docs/` is the user's and stays untracked.
- **The GitHub repo is public** (the GitHub API says `"private": false`). Keep secrets, customer
  data, personal paths and other clients' names out of commits, deploy files and PRs.
- **Cloud Run Phase 1 (code) and the Phase 2 code are done** on `feat/cloud-run`. Nothing is
  deployed. The only GCP resource created is the Agent Engine `khind-sales-sessions`.
- **Checks on `feat/cloud-run`**, all passing:
  - offline: `unit_checks.py` 158, `session_checks.py` 13, `webhook_checks.py` 43. The webhook checks
    caught all 11 deliberate code breaks (a mutation test);
  - online: `session_online.py` 8 (two real Gemini turns on `khind-sales-sessions`);
  - end to end: `replay_local.py` 10 (the app on a local port, signed calls, a mock Chatwoot, real
    Gemini, RAG, GCS media and Agent Engine);
  - the container, checked without Docker (no Docker daemon runs in WSL): a clean Python 3.12 env
    from `requirements.txt` and `constraints.txt`, started from a folder that holds only `apps/`.

## User decisions (2026-09-24)

- Rerun 3 was the last smoke test. Its findings are open issues, not fixes in the flow PR.
- Push `feat/linear-sales-flow` and open a PR to `main` (approved).
- Cloud Run:
  - **D1:** stay in `prudential-poc-484904`.
  - **D2:** a new Agent Engine for KHIND sessions. Created: `khind-sales-sessions`, ID
    `5343705675828559872`, asia-southeast1. `.env` points at it. The engine that `.env` named
    before belongs to another app: leave it alone.
  - **D3:** check Chatwoot's signature. This was the plan's own rule, because Chatwoot v4.18.0 signs
    agent-bot calls with the bot's Webhook Secret.
  - **D4:** staging uses a separate test inbox (with its own WhatsApp number and agent bot). The user
    sets it up; it does not exist yet.
  - After a handoff, a chat that is pending again resumes the flow.
- Not yet approved: creating any other GCP resource, and any deploy.

## Next steps, in order

1. **PR for the flow.** The user runs `git push -u origin feat/linear-sales-flow` in their own
   terminal (WSL git has no credentials; `gh` is not installed). Then they open
   `https://github.com/BobbyAxelrods/agentic-sales-adk-khind/compare/main...feat/linear-sales-flow?expand=1`
   with the title `feat(flow): linear WhatsApp sales flow, smoke test 62 of 62` and the body from
   `handoff/2026-09-24-pr-description.md`. Record the PR URL here and in CLAUDE.md "History".
2. **Push `feat/cloud-run`** too (same way). Open its PR after the flow PR is merged, so its diff
   shows only the Cloud Run work.
3. **Ask the user to approve the GCP resources** in Phase 2, then create them.
4. **The user sets up staging in Chatwoot:** the test inbox, an agent bot connected to it (any
   outgoing URL for now), and the bot's access token and Webhook Secret in Secret Manager.
5. **Deploy staging** (Phase 3, needs approval), set the bot's outgoing URL, then run the WhatsApp
   smoke test.
6. **Production:** the same steps with the live bot's secrets, then switch the live bot's URL.

## Plan: publish the agent to Cloud Run

The target is the Chatwoot webhook app (`apps/main.py`, FastAPI, `POST /webhook`), called by the
Chatwoot agent bot of the inbox. ADK Web is a test UI only: never deploy it in public.
`adk deploy cloud_run` deploys the ADK dev server, not this app.

### Phase 1: make the webhook path work (done on `feat/cloud-run`)

- `9c5fd18`: the model retries transient Vertex AI errors (G5 of rerun 3); `tenacity` is in
  `requirements.txt`.
- `9eb7ed0`: the durable session layer and the new webhook (details in CLAUDE.md "Where the flow is
  enforced"): signed calls only, the event filter, 200 at once with the turn in the background, one
  turn at a time per chat, repeats skipped, no pending toggles, resume after a handoff, the IC-photo
  handoff, no second product list, labels added (not replaced).
- `282f8f4`: settings values are stripped of surrounding whitespace (secrets pasted with a newline).
- What the Chatwoot v4.18.0 source says (Chatwoot Cloud reports 4.18.0 at `/api`):
  - `lib/webhooks/trigger.rb`: 5 s timeout (installation config `WEBHOOK_TIMEOUT`). Agent-bot calls
    are retried only on 429 and 500 (3 attempts, the same `X-Chatwoot-Delivery`). On any failure
    of a message event, a pending chat is opened with the activity message "Conversation was marked
    open by system due to an error with the agent bot". This is why the old code set every chat
    back to pending: its turns took longer than 5 s.
  - The signature: `X-Chatwoot-Signature: sha256=<hex HMAC-SHA256(secret, "<ts>.<body>")>` and
    `X-Chatwoot-Timestamp`, for account, agent-bot and API-inbox webhooks (agent bots since v4.13).
  - `app/listeners/agent_bot_listener.rb` and `Message#webhook_sendable?`: the bot receives
    incoming, outgoing and template messages, `message_updated`, and conversation events, with no
    status check.
  - `app/controllers/concerns/access_token_auth_helper.rb`: what a bot token may call.
  - `app/models/message.rb`: a resolved chat in an inbox with an active bot goes back to `pending`
    when the customer writes (`reopen_resolved_conversation`).
- The `.env` token is an agent bot token: `/profile` and `/inboxes` answer "not authorized for bots".

### Phase 2: container and GCP setup

Done on `feat/cloud-run` (`121d44b`):
- `Dockerfile` (python:3.12-slim, non-root, uvicorn on `$PORT`), `.dockerignore`, and
  `.gcloudignore`, an allow list. `gcloud meta list-files-for-upload` shows only the Dockerfile,
  the two requirement files and `apps/` code: no `.env`, no key file, no `apps/.adk`.
- `constraints.txt` pins all 119 packages to the tested `.venv`.
- At shutdown the app waits up to 8 s for running turns.

To do, **after the user approves** (all in `prudential-poc-484904`):

```
PROJECT=prudential-poc-484904
SA=khind-sales-agent@$PROJECT.iam.gserviceaccount.com
gcloud iam service-accounts create khind-sales-agent --project $PROJECT \
  --display-name "KHIND sales agent (Cloud Run runtime)"
gcloud projects add-iam-policy-binding $PROJECT --member serviceAccount:$SA \
  --role roles/aiplatform.user --condition None        # Gemini, RAG, Agent Engine sessions
gcloud storage buckets add-iam-policy-binding gs://khind_2028 --member serviceAccount:$SA \
  --role roles/storage.objectViewer                    # product media
for s in khind-staging-chatwoot-api-token khind-staging-chatwoot-webhook-secret; do
  gcloud secrets create $s --project $PROJECT --replication-policy user-managed --locations asia-southeast1
  gcloud secrets add-iam-policy-binding $s --project $PROJECT --member serviceAccount:$SA \
    --role roles/secretmanager.secretAccessor
done
```

- Use no JSON key for the service account.
- The user adds the secret values in their own terminal, so the values never pass through a chat:
  `gcloud secrets versions add khind-staging-chatwoot-api-token --data-file=-`, paste, then
  Ctrl-D.
- Cloud Run, Cloud Build, Artifact Registry (`cloud-run-source-deploy`) and Secret Manager are
  already enabled.
- Open question: should staging use its own Agent Engine (for example
  `khind-sales-sessions-staging`), so test chats never share a store with customer chats?

### Phase 3: deploy, staging first (needs approval)

```
gcloud run deploy khind-sales-agent-staging --source . --region asia-southeast1 \
  --project prudential-poc-484904 --service-account $SA --allow-unauthenticated \
  --min-instances 1 --max-instances 1 --no-cpu-throttling --cpu 1 --memory 1Gi --timeout 60 \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=prudential-poc-484904,\
GOOGLE_CLOUD_LOCATION=asia-southeast1,LLM_MODEL=gemini-2.5-flash,RAG_CORPUS_NAME=<from .env>,\
GCS_BUCKET=khind_2028,VERTEX_AI_AGENT_ENGINE_ID=<engine ID>,CHATWOOT_BASE_URL=https://app.chatwoot.com,\
CHATWOOT_ACCOUNT_ID=<from .env>,CHATWOOT_HUMAN_AGENT_ID=<officer for staging handoffs> \
  --set-secrets CHATWOOT_API_TOKEN=khind-staging-chatwoot-api-token:latest,\
CHATWOOT_WEBHOOK_SECRET=khind-staging-chatwoot-webhook-secret:latest
```

- `--allow-unauthenticated`: Chatwoot cannot send Google identity tokens; the signature is the guard.
- `--min-instances 1`: a cold start is longer than Chatwoot's 5 s, and a late response opens the chat.
- `--no-cpu-throttling`: the turn runs after the response, so the CPU must stay on.
- `--max-instances 1`: the per-chat turn lock is in process memory.
- Do not set `GOOGLE_APPLICATION_CREDENTIALS` or `PORT`.
- Cost: an always-on instance with 1 vCPU and 1 GiB costs very roughly USD 50-70 a month per
  service (check the asia-southeast1 price). Scale staging to 0 instances or delete it after the
  tests.

Then:
1. Set the test bot's outgoing URL to `https://<service URL>/webhook`.
2. Smoke test on WhatsApp:
   - the happy path (A1 to A11), and the media order: 2 images and 1 video, then the text;
   - an uncovered area (B2), not working (F3), a request for a human (F1), a product question (D1);
   - after each handoff: the chat is open, the label is added, the note and the assignment are
     there, and the bot stays silent;
   - resolve a handed-over chat and write again: the bot resumes;
   - the IC photos after the form: a `human-required` handoff and `IC_PHOTOS_RECEIVED_LINE`;
   - the chat stays `pending` after bot replies, and there is no "marked open by system due to an
     error with the agent bot" message;
   - Cloud Logging: no errors, no "ADK runner failed", and no "without a valid Chatwoot signature".
     That last log line means the secret does not match the bot's Webhook Secret.
3. Production: deploy `khind-sales-agent` from the same source with the live bot's secrets
   (`khind-chatwoot-api-token`, `khind-chatwoot-webhook-secret`), check it the same way, then
   switch the live bot's outgoing URL. Rollback: point the bot back, or
   `gcloud run services update-traffic khind-sales-agent --to-revisions <previous>=100`.

### Phase 4: operate

- Alerts on the 5xx rate, on "ADK runner failed" and on "Webhook background task failed".
- A budget alert for Vertex AI and Cloud Run spend.
- Optional: a Cloud Build trigger on `main`.

### Before go-live, outside the code (KHIND or the team)

- Create the `not-working` label in Chatwoot.
- Approve `IC_PHOTOS_RECEIVED_LINE`, and choose a label for IC photos if `human-required` is too
  broad.
- Set a retention time for sessions (PDPA). Agent Engine sessions accept a TTL.
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
3. A WhatsApp interactive product list (Chatwoot `input_select`) could replace the text list. The
   reply would still arrive as text.

## Read these instead of re-deriving

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls (including Chatwoot's) and open
  issues.
- `git log main..feat/cloud-run` and `git show 9eb7ed0` for the webhook and session work.
- `handoff/verification/`:
  - offline: `unit_checks.py` (158), `session_checks.py` (13), `webhook_checks.py` (43);
  - online: `session_online.py` (the real Agent Engine and Gemini; deletes its test session);
  - end to end: `replay_local.py` (the app and a mock Chatwoot on local ports; deletes its test
    session);
  - `scenarios.py`: 17 real-Gemini scenarios with 64 checks, run against `adk api_server` on
    port 8001;
  - `extract_run.py`, `trace_run.py` and `check_run.py` for audits of an ADK Web run.
- `handoff/smoke-test/`: the builder, the v2 csv and xlsx, the guide and the Astra prompt.
- The shared test report (private until the user shares it):
  `https://claude.ai/artifact/3sXrGyfVs2kE1GWw64jYeA`. Edit it with the Claude Docs connector.

## Suggested skills

- `simple-english`: CLAUDE.md, this file and the Obsidian notes use short, plain English.
- `security-review`: before the service gets a public URL.
- `run`: to start the app locally. Use `replay_local.py`, never the live `.env` Chatwoot values.
- `handoff`: write the next handoff into this same file.

## Environment

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0`, and `gemini-2.5-flash`
  with a thinking budget of 1024. `uv` is installed. `openpyxl` is not in `.venv`; use
  `uv run --no-project --with openpyxl ...`.
- `gcloud` is logged in to project `prudential-poc-484904`. Leave the project's other Cloud Run
  service, Artifact Registry repos, secrets and the other Agent Engine alone: they belong to other
  apps.
- The `docker` CLI is installed, but no Docker daemon runs in WSL. Cloud Build builds the image at
  deploy time.
- ADK Web runs on port 8000 (started by the user). Run verification servers on port 8001 with
  `--session_service_uri memory://`. Follow the `pkill` rules in CLAUDE.md.
- `gh` is not installed; git in WSL has no credential helper.
- Secrets live in the git-ignored `.env` and the service-account JSON. Never print or copy them. The
  `.env` Chatwoot token and secret belong to the live agent bot. The test prompts use fictional
  identity data only.

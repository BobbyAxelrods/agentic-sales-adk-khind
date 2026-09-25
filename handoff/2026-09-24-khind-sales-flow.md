# Handoff: KHIND sales agent. Next: deploy on Cloud Run (staging, then production)

Earlier versions of this file are in git history:
- `cc153b1`: the first v2 run;
- `de4f6c9`: the fix round;
- `d91a9ab`: rerun 2 (58/62) and its fix directions;
- `5be9410`: before rerun 3;
- `93691df`: rerun 3 done, before its audit;
- `2e4d1a6`: rerun 3 audited, before the Cloud Run plan;
- `e56ebb6`: the Cloud Run plan, before Phase 1;
- `bce6f69`: Phase 2 resources created, before the staging-first version;
- `da37817`: the staging-first version, before the 2026-09-25 pre-deploy checks;
- `1bef4df`: the 2026-09-25 checks, before this runbook for a helper.

Rules, enforcement points, pitfalls and open issues are in `CLAUDE.md`; this file does not repeat
them.

## Start here: the deploy runbook

Anyone can follow this runbook: the owner or a helper, a person or an agent. **The owner** (called
"the user" in older notes) runs this project, gives access and approves each deploy. The Chatwoot
steps were checked against the Chatwoot v4.18.0 source (Chatwoot Cloud runs it). The gcloud steps
were checked with gcloud 560.

**Goal:** `khind-sales-agent-staging` runs on Cloud Run and passes a WhatsApp smoke test on a test
inbox. Then `khind-sales-agent` takes over the live bot.

**Status on 2026-09-25:** the GCP resources exist and pass every pre-deploy check ("Where things
stand"). Parts A to E are not done: both staging secrets have 0 versions. Nothing is deployed.

**Rules for everyone:**
- This repo is public. Never commit or paste a token, a secret, customer data or the project
  number. With the project number, anyone can derive the webhook URLs.
- Never press **Reset** on a bot's Access Token or Webhook Secret. Reset makes a new value, and the
  service stops working until Secret Manager has it.
- Do not change the live inbox or the live bot before "Production". Leave the project's other apps
  alone (see "Infra").
- Tests use fictional names, IC numbers and phone numbers only.

### 0. Access and inputs (the owner gives these)

| For | What |
|---|---|
| A, B, D, E | Administrator on KHIND's Chatwoot account (the account of the live inbox). Only administrators see the Bots page and a bot's values. |
| A | A spare SIM or eSIM for the test inbox. It must get the code by SMS or call. Best: a number that was never on WhatsApp. A number on personal WhatsApp: delete that WhatsApp account first. A number on the WhatsApp Business app: only "Quick setup" can connect it. |
| A | Admin on the Meta business portfolio that will own the test number. |
| G | A second phone with WhatsApp, as the customer. |
| C, F, H | The GCP roles below, on project `prudential-poc-484904`. |
| F | Two Chatwoot IDs (not secrets): the account ID (in the Chatwoot URL, `/app/accounts/<id>/`) and the officer's agent ID. The owner's `.env` has both (`CHATWOOT_ACCOUNT_ID`, `CHATWOOT_HUMAN_AGENT_ID`). |
| F | `gcloud` and `git`, and this repo on branch `feat/cloud-run`. No `.env`, key file or Docker: Cloud Build builds the image. |

GCP roles for a helper. The owner runs this, with the helper's email:

```
H=user:helper@example.com; P=prudential-poc-484904
for r in roles/run.sourceDeveloper roles/run.admin roles/logging.viewer roles/secretmanager.viewer; do
  gcloud projects add-iam-policy-binding $P --member=$H --role=$r --condition=None
done
gcloud iam service-accounts add-iam-policy-binding khind-sales-agent@$P.iam.gserviceaccount.com \
  --member=$H --role=roles/iam.serviceAccountUser --project $P
for s in khind-staging-chatwoot-api-token khind-staging-chatwoot-webhook-secret; do
  gcloud secrets add-iam-policy-binding $s --member=$H --role=roles/secretmanager.secretVersionAdder --project $P
done
```

- `run.sourceDeveloper` builds and deploys from source, but it cannot set the service's IAM policy.
  `run.admin` can, and `--allow-unauthenticated` needs it. Without it the deploy only warns, and
  Chatwoot gets 403.
- Service Account User lets the service run as `khind-sales-agent`.
- For "Production", the helper also needs `roles/secretmanager.admin`, or the owner creates the 2
  production secrets.
- Remove the roles after the deploy.

### A. Chatwoot: the test WhatsApp inbox (15–30 min)

1. **Settings → Inboxes → Add Inbox → WhatsApp**.
2. Under **API Provider**, choose one:
   - **WhatsApp Business** ("Quick setup with Meta"): the easiest. Log into Meta, choose the
     business, then add and verify the number. Chatwoot sets up Meta's webhook itself.
   - **WhatsApp Cloud** (manual), if Quick setup is not offered or fails. The wizard shows these
     steps:
     1. In Meta Developers, create an app with the WhatsApp use case. Click **My Meta app is
        ready**.
     2. In the app, open **WhatsApp → API Setup → From → Add phone number**. Fill in the business
        profile and enter the code. Copy the **Phone Number ID** and the **WhatsApp Business
        Account ID**.
     3. In Meta Business Settings, open **Users → System users**. Create an admin system user, and
        give it the app and the WhatsApp Business Account with full control. Click **Generate
        token**: expiration **Never**, permissions `whatsapp_business_management` and
        `whatsapp_business_messaging`. Meta shows the token only once.
     4. Paste the 3 values and click **Verify details**. Name the inbox, for example "KHIND Sales
        (staging)", and click **Create inbox**. Wait until the 4 checks show **Verified**. If one
        stays Pending, click **Retry webhook setup**.
3. Click **Continue to add agents**. Add the owner and **the officer who gets the live handoffs**
   (`CHATWOOT_HUMAN_AGENT_ID`). A handoff assigns the chat to that officer. An agent who is not an
   administrator can open a chat only in their own inboxes: the assignment alone is not enough.

### B. Chatwoot: the staging bot (5 min)

1. **Settings → Bots → Add Bot**.
2. **Bot name:** `KHIND Sales Agent (staging)`. **Webhook URL:**
   `https://khind-sales-agent-staging-<project number>.asia-southeast1.run.app/webhook`.
   Get the project number with
   `gcloud projects describe prudential-poc-484904 --format='value(projectNumber)'`. Cloud Run
   gives the service this URL at the deploy, so the bot needs no change later.
3. Click **Create Bot**. The dialog shows the **Access Token** and the **Webhook Secret**. Keep it
   open for Part C. Later, both are under **Bots →** edit the bot.

### C. Secret Manager: the bot's 2 values (2 min)

Do this in a terminal, never in a chat or a ticket. Run each command, paste the value, press
Enter, then press Ctrl-D:

```
gcloud secrets versions add khind-staging-chatwoot-api-token --project prudential-poc-484904 --data-file=-
gcloud secrets versions add khind-staging-chatwoot-webhook-secret --project prudential-poc-484904 --data-file=-
```

The first secret gets the **Access Token**, the second the **Webhook Secret**. Each command prints
`Created version [1]`. The app strips the trailing newline.

### D. Chatwoot: connect the bot (1 min)

**Settings → Inboxes →** the test inbox **→ Bot Configuration**. Select
`KHIND Sales Agent (staging)` and click **Update**. New chats in this inbox now start `pending`,
with the bot in charge.

**Do not message the test number before Part F passes.** Until then, Chatwoot's call to the bot
fails, and Chatwoot opens the chat for officers.

### E. Chatwoot: labels (2 min, once for the account)

**Settings → Labels.** Make sure these 5 labels exist, and add the missing ones (`not-working` is
new): `coverage-unsupported-alternative`, `not-working`, `human-required`, `angry-customer`,
`rag-error`. The handoffs add them, and a label must exist here to show in filters.

### F. Deploy staging (after the owner approves; ~15 min)

1. Check, without printing any value:
   - each staging secret has 1 version:
     `gcloud secrets versions list khind-staging-chatwoot-api-token --project prudential-poc-484904`,
     and the same for `khind-staging-chatwoot-webhook-secret`;
   - `git status` shows branch `feat/cloud-run` with a clean tree.

   The other pre-deploy checks and the security review passed on 2026-09-25 ("Where things
   stand"). Do them again only if `apps/`, `Dockerfile`, `.gcloudignore`, the requirements or IAM
   changed after that.
2. **Get the owner's approval.** Staging costs about USD 62 a month while it runs, about USD 15 for
   one test week.
3. Run "Staging deploy command" from the repo root. The first build takes about 5 minutes.
4. Check the service. Each line shows the expected result:

   ```
   URL=https://khind-sales-agent-staging-$(gcloud projects describe prudential-poc-484904 --format='value(projectNumber)').asia-southeast1.run.app
   curl -s $URL/health                                                    # {"status":"ok"}
   curl -s -o /dev/null -w '%{http_code}\n' -X POST $URL/webhook -d '{}'  # 401
   gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="khind-sales-agent-staging"' \
     --project prudential-poc-484904 --freshness 30m --format='value(textPayload)' \
     | grep -E 'is not set|not configured|Traceback' || echo clean                # clean
   ```

   The 401 shows that unsigned calls are refused. The call gets 401 also when the secret is
   missing, so only `clean` shows that the secret is loaded. If `$URL` does not answer, list the
   service's URLs and correct the bot's Webhook URL:
   `gcloud run services describe khind-sales-agent-staging --region asia-southeast1 --project prudential-poc-484904 --format="value(metadata.annotations['run.googleapis.com/urls'])"`.

### G. Staging smoke test (~1 hour)

From the second phone, message the test number. Follow "Staging smoke test" below. Afterwards,
the owner chooses: scale staging to 0, or delete it ("Staging deploy command" has both commands).

### H. Production (after staging passes)

Follow "Production" below.

## Where things stand (2026-09-25)

- **GitHub** (public repo; keep secrets, customer data, personal paths and other clients' names out
  of commits and PRs):
  - Both branches are on GitHub: `feat/linear-sales-flow` (`e56ebb6`) and `feat/cloud-run`. The
    owner pushes. **No PR is open yet.**
  - The flow PR: open
    `https://github.com/BobbyAxelrods/agentic-sales-adk-khind/compare/main...feat/linear-sales-flow?expand=1`
    with the title `feat(flow): linear WhatsApp sales flow, smoke test 62 of 62` and the body from
    `handoff/2026-09-24-pr-description.md`.
  - The Cloud Run PR: after the flow PR is merged, from `feat/cloud-run`, with the title
    `feat(deploy): Cloud Run-ready Chatwoot webhook` and the body from
    `handoff/2026-09-24-pr-cloud-run.md`.
  - Record each PR URL here and in CLAUDE.md "History".
  - `docs/` is the user's and stays untracked.
- **Code:** Cloud Run Phase 1 and the container are done on `feat/cloud-run` (details below).
- **GCP:** the approved resources exist (see "Infra"). Nothing is deployed, and on 2026-09-25 the
  staging secrets were still empty.
- **Pre-deploy checks on `da37817` (2026-09-25)**, all passing:
  - the upload set is 21 files: `Dockerfile`, `.dockerignore`, `requirements.txt`,
    `constraints.txt` and `apps/`. It has no `.env`, key file or `apps/.adk`, and every tracked
    file under `apps/` is in it.
  - the service account has 0 keys and only its 3 grants. Each staging secret grants
    `secretAccessor` to it only.
  - both Agent Engines exist with 0 sessions, the RAG corpus is active, the 8 APIs are enabled,
    and the deployer is a project owner.
  - `.env` holds both IDs that the deploy command reads, and gcloud 560 accepts every flag.
- **Security review (2026-09-25):** no findings, on the code diff `main...da37817`. Checked:
  - the signature check: it fails closed, signs the raw body, uses `compare_digest`, allows ±300 s,
    and runs before any parsing;
  - the routes: `/`, `/health` and `/webhook`, plus FastAPI's default `/docs`, `/redoc` and
    `/openapi.json`, which show only the route schema;
  - payload values that reach a URL, a path or a parser; tools act only on their own chat;
  - the logs: no secret, message text or personal data;
  - the container: non-root, and allow lists for the upload and the image.
- **Checks on `feat/cloud-run`**, all passing:
  - offline: `unit_checks.py` 158, `session_checks.py` 13, `webhook_checks.py` 43 (it caught all
    11 deliberate code breaks). Run again on 2026-09-25: all pass;
  - online: `session_online.py` 8, with real Gemini turns on `khind-sales-sessions`;
  - end to end: `replay_local.py` 10: the app on a local port, signed calls, a mock Chatwoot, and
    real Gemini, RAG, media and Agent Engine;
  - the container steps, without Docker (no Docker daemon runs in WSL).

## Infra (project `prudential-poc-484904`, asia-southeast1; read live on 2026-09-25)

Nothing is deployed on Cloud Run yet. The times are UTC, from each resource's create time.

| Created | Resource | Name | Status | Used for |
|---|---|---|---|---|
| 2026-09-11 17:22 | Storage bucket | `khind_2028` (25 objects, 53 MB) | in use | Product images and videos |
| 2026-09-12 03:09 | RAG corpus | `khind`, `2305843009213693952` (10 files; 2 are old duplicates) | active | The product documents |
| 2026-09-24 10:45 | Agent Engine (production) | `khind-sales-sessions`, `5343705675828559872` | 0 sessions | Chat history and state; `.env` points at it |
| 2026-09-24 11:28 | Service account | `khind-sales-agent` | 0 keys | Runtime identity: `aiplatform.user` on the project, `storage.objectViewer` on `khind_2028`, `secretAccessor` on the 2 staging secrets |
| 2026-09-24 11:28 | Secrets (staging) | `khind-staging-chatwoot-api-token`, `khind-staging-chatwoot-webhook-secret` | **0 versions (empty)** | The test bot's token and Webhook Secret |
| 2026-09-24 11:28 | Agent Engine (staging) | `khind-sales-sessions-staging`, `3247842999241015296` | 0 sessions | Test chats, apart from customer data |
| not yet | Cloud Run (staging) | `khind-sales-agent-staging` | needs approval | The webhook app for the test inbox |
| not yet | Cloud Run (production) | `khind-sales-agent` | after staging passes | The webhook app for the live inbox |
| not yet | Secrets (production) | `khind-chatwoot-api-token`, `khind-chatwoot-webhook-secret` | to create | The live bot's values (today in `.env`) |

- Shared with the project's other apps: the RAG database (Spanner, Basic tier), the Artifact
  Registry repo `cloud-run-source-deploy` and Cloud Build. They hold no KHIND image or build yet.
- Leave the project's other apps alone: their Cloud Run service, Artifact Registry repos, secrets,
  RAG corpora and Agent Engine.
- To see what changed, read the Admin Activity audit log. Vertex AI logs a create against the
  region, not the name, so Agent Engines and RAG corpora need the second command:

```
gcloud logging read 'logName:"cloudaudit.googleapis.com%2Factivity" AND "khind" AND timestamp>="2026-09-01T00:00:00Z"' \
  --project prudential-poc-484904 --order asc --format="value(timestamp,protoPayload.methodName,protoPayload.resourceName)"
gcloud logging read 'logName:"cloudaudit.googleapis.com%2Factivity" AND protoPayload.serviceName="aiplatform.googleapis.com" AND protoPayload.methodName=~"Create|Delete" AND timestamp>="2026-09-01T00:00:00Z"' \
  --project prudential-poc-484904 --order asc --format="value(timestamp,protoPayload.methodName)"
```

## Cost (USD list prices for Singapore, checked 2026-09-24)

| Item | Cost |
|---|---|
| KHIND's own resources today | ~$0 a month |
| The shared RAG database (Spanner, Basic tier, 6 corpora of which 5 are other apps') | ~$103 a month, already billing |
| One always-on Cloud Run service (1 vCPU, 1 GiB, CPU always on) | ~$62 a month; ~$15 for one test week |
| Gemini per full 12-turn sales chat (measured: 138K input tokens, half cached; 2.1K output) | ~$0.03 |
| Media per product pick (~6 MB sent to Chatwoot) | ~$0.001 |
| Secrets, images, logs, sessions storage, bucket | ~$1 a month together |

- Production at 2,000 full chats a month: about $123 a month, plus the shared RAG database.
- Agent Engine session billing started on 2026-09-01: storage is $0.30 per GiB-month after the free
  1 GiB, so 64 KB per chat is negligible.
- Not included: the Chatwoot plan and Meta's WhatsApp fees.
- A saving for later: run the turns through Cloud Tasks instead of in-process background tasks. The
  warm instance then bills at the idle rate (about $18 instead of $62). About 1 day of work.

## Staging deploy command (after approval)

Run from the repo root on `feat/cloud-run`. Nothing here prints a secret. The two Chatwoot IDs are
not secrets. The command reads them from the owner's `.env`. Without `.env`, set them by hand
first (Part 0), and the block keeps them.

```
PROJECT=prudential-poc-484904
SA=khind-sales-agent@$PROJECT.iam.gserviceaccount.com
[ -f .env ] && ACCOUNT_ID=$(grep '^CHATWOOT_ACCOUNT_ID=' .env | cut -d= -f2-)
[ -f .env ] && OFFICER_ID=$(grep '^CHATWOOT_HUMAN_AGENT_ID=' .env | cut -d= -f2-)
if [ -z "$ACCOUNT_ID" ] || [ -z "$OFFICER_ID" ]; then echo "Set ACCOUNT_ID and OFFICER_ID first"; else
gcloud run deploy khind-sales-agent-staging --source . --region asia-southeast1 --project $PROJECT \
  --service-account $SA --allow-unauthenticated --quiet \
  --min-instances 1 --max-instances 1 --no-cpu-throttling --cpu 1 --memory 1Gi --timeout 60 \
  --labels app=khind-sales-agent,env=staging \
  --set-env-vars "GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT,\
GOOGLE_CLOUD_LOCATION=asia-southeast1,LLM_MODEL=gemini-2.5-flash,\
RAG_CORPUS_NAME=projects/$PROJECT/locations/asia-southeast1/ragCorpora/2305843009213693952,\
GCS_BUCKET=khind_2028,VERTEX_AI_AGENT_ENGINE_ID=3247842999241015296,\
CHATWOOT_BASE_URL=https://app.chatwoot.com,CHATWOOT_ACCOUNT_ID=$ACCOUNT_ID,\
CHATWOOT_HUMAN_AGENT_ID=$OFFICER_ID" \
  --set-secrets "CHATWOOT_API_TOKEN=khind-staging-chatwoot-api-token:latest,\
CHATWOOT_WEBHOOK_SECRET=khind-staging-chatwoot-webhook-secret:latest"
fi
```

- `--allow-unauthenticated`: Chatwoot cannot send Google identity tokens. The signature check is
  the guard.
- `--min-instances 1`: a cold start takes longer than Chatwoot's 5 s, and a late response opens the
  chat for officers.
- `--no-cpu-throttling`: the turn runs after the 200, so the CPU must stay on.
- `--max-instances 1`: the per-chat turn lock is in process memory.
- `--labels`: Billing > Reports can then show this service's cost on its own.
- Do not set `GOOGLE_APPLICATION_CREDENTIALS` or `PORT`.
- Stop the cost after the tests:
  `gcloud run services update khind-sales-agent-staging --min-instances 0 --region asia-southeast1 --project prudential-poc-484904`,
  or `gcloud run services delete ...`. With 0 instances, a message after an idle period can
  wait for a cold start, and Chatwoot then opens the chat.

## Staging smoke test (WhatsApp, test inbox)

Send the messages from the second phone. The IDs are rows of
`handoff/smoke-test/KHIND_Agent_Smoke_Test_Prompts_v2.csv`: each row has the message, its
precondition and the expected reply. The rows were written for ADK Web, but the messages are the
same on WhatsApp. Watch the chat in Chatwoot at the same time.

1. The happy path (A1 to A11). On the first pick, 2 images and 1 video arrive before the text.
2. The handoffs: an uncovered area (B2), not working (F3) and a request for a human (F1). After
   each: the chat is open, the label is added next to any existing ones, the note and the
   assignment are there, and the bot stays silent.
3. Resolve a handed-over chat and write again: the bot resumes the flow.
4. After the form: IC photos give a `human-required` handoff and `IC_PHOTOS_RECEIVED_LINE`.
5. Throughout:
   - the chat stays `pending` after bot replies;
   - there is no "marked open by system due to an error with the agent bot" message;
   - Cloud Logging shows no errors and no "ADK runner failed". A "without a valid Chatwoot
     signature" line means the secret does not match the bot's Webhook Secret.

## Production (after staging passes)

1. Create the 2 production secrets, like the staging ones, and let the service account read them:

   ```
   P=prudential-poc-484904; SA=khind-sales-agent@$P.iam.gserviceaccount.com
   for s in khind-chatwoot-api-token khind-chatwoot-webhook-secret; do
     gcloud secrets create $s --project $P --replication-policy=user-managed \
       --locations=asia-southeast1 --labels=app=khind-sales-agent,env=production
     gcloud secrets add-iam-policy-binding $s --project $P \
       --member=serviceAccount:$SA --role=roles/secretmanager.secretAccessor
   done
   ```

2. Add the **live** bot's Access Token and Webhook Secret, as in Part C, to these 2 secrets. They
   are in Chatwoot, **Settings → Bots →** edit the live bot. Never press Reset on the live bot.
3. **Get the owner's approval** (about USD 62 a month). Deploy `khind-sales-agent` with the staging
   command. Change these: the service name, `env=production`,
   `VERTEX_AI_AGENT_ENGINE_ID=5343705675828559872`, and the 2 production secret names.
4. Check it as in Part F, with `khind-sales-agent` in the URL and in the log filter.
5. Write down the live bot's current Webhook URL: it is the rollback. Then set it to
   `https://khind-sales-agent-<project number>.asia-southeast1.run.app/webhook`.
6. Rollback: put the old URL back on the live bot, or
   `gcloud run services update-traffic khind-sales-agent --to-revisions <previous>=100 --region asia-southeast1 --project prudential-poc-484904`.
7. Then Phase 4: alerts on the 5xx rate, "ADK runner failed" and "Webhook background task
   failed", and a budget alert.

## User decisions (2026-09-24)

- Rerun 3 was the last smoke test. Its findings are open issues, not fixes in the flow PR.
- Cloud Run:
  - **D1:** stay in `prudential-poc-484904`.
  - **D2:** a new Agent Engine for KHIND sessions (`khind-sales-sessions`). The engine that `.env`
    named before belongs to another app: leave it alone.
  - **D3:** check Chatwoot's signature (Chatwoot v4.18.0 signs agent-bot calls).
  - **D4:** staging uses a separate test inbox with its own WhatsApp number and agent bot. The
    owner or a helper sets it up (runbook Parts A to E).
  - After a handoff, a chat that is pending again resumes the flow.
  - The Phase 2 resources: approved and created.
  - Staging keeps its sessions in its own engine, `khind-sales-sessions-staging`.
  - Staging handoffs go to the same officer as in `.env` (`CHATWOOT_HUMAN_AGENT_ID`).
  - **The staging deploy needs a fresh approval** ("ask me again first").

## What was built (Phases 1 and 2, on `feat/cloud-run`)

- `9c5fd18`: the model retries transient Vertex AI errors (G5 of rerun 3), and `tenacity` is in
  `requirements.txt`.
- `9eb7ed0`: the durable session layer and the new webhook (see CLAUDE.md "Where the flow is
  enforced"). It adds signed calls only, the event filter, and 200 at once with the turn in the
  background. It also runs one turn at a time per chat, skips repeats, and drops the pending
  toggles. A chat resumes after a handoff, IC photos hand over, the second product list is gone,
  and labels are added, not replaced.
- `121d44b`: the `Dockerfile` (python:3.12-slim, non-root) and `.dockerignore`. Also
  `.gcloudignore`, an allow list: `gcloud meta list-files-for-upload` shows no `.env`, key file or
  `apps/.adk`. And `constraints.txt` (119 pinned packages). At shutdown the app waits up to 8 s
  for running turns.
- `282f8f4`: settings values are stripped of surrounding whitespace.
- What the Chatwoot v4.18.0 source says (Chatwoot Cloud reports 4.18.0 at `/api`):
  - `lib/webhooks/trigger.rb`:
    - 5 s timeout.
    - Agent-bot calls are retried only on 429 and 500.
    - On a failure of a message event, a pending chat is opened.
  - The signature: `X-Chatwoot-Signature: sha256=<hex HMAC-SHA256(secret, "<ts>.<body>")>` and
    `X-Chatwoot-Timestamp` (agent bots since v4.13).
  - `app/listeners/agent_bot_listener.rb`: the bot receives incoming, outgoing and template
    messages, `message_updated`, and conversation events, with no status check.
  - `app/controllers/concerns/access_token_auth_helper.rb`: what a bot token may call.
  - `app/models/message.rb`: a resolved chat in an inbox with an active bot goes back to `pending`
    when the customer writes.
- The `.env` token is an agent bot token (the live bot's).

## Before go-live, outside the code (KHIND or the team)

- Create the `not-working` label in Chatwoot (runbook Part E).
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

- `CLAUDE.md`: the flow, where each rule is enforced, pitfalls (including Chatwoot's and the RAG
  database's) and open issues.
- `git log main..feat/cloud-run` and `git show 9eb7ed0` for the webhook and session work.
- `handoff/verification/`:
  - offline: `unit_checks.py` (158), `session_checks.py` (13), `webhook_checks.py` (43);
  - online: `session_online.py` (the real Agent Engine and Gemini; deletes its test session);
  - end to end: `replay_local.py` (the app and a mock Chatwoot on local ports; deletes its test
    session);
  - `scenarios.py`: 17 real-Gemini scenarios with 64 checks, against `adk api_server` on port 8001;
  - `extract_run.py`, `trace_run.py` and `check_run.py` for audits of an ADK Web run.
- `handoff/smoke-test/`: the builder, the v2 csv and xlsx, the guide and the Astra prompt.
- The shared test report (private until the user shares it):
  `https://claude.ai/artifact/3sXrGyfVs2kE1GWw64jYeA`. Edit it with the Claude Docs connector.

## Suggested skills

- `i-have-adhd:i-have-adhd`: the user asked for this answer style on 2026-09-24. Lead with the
  next action, use numbered steps, give concrete time and cost figures, and restate where things
  stand.
- `simple-english`: CLAUDE.md, this file and the Obsidian notes use short, plain English.
- `security-review`: done on 2026-09-25 (no findings). Run it again if the code changes before
  the staging service gets its public URL.
- `handoff`: write the next handoff into this same file.

## Environment (the owner's machine)

A helper who only deploys needs none of this: see runbook Part 0.

- WSL2 (`Ubuntu-22.04`), `.venv` with Python 3.12, `google-adk==1.31.0`, and `gemini-2.5-flash`
  with a thinking budget of 1024. `uv` is installed. `openpyxl` is not in `.venv`; use
  `uv run --no-project --with openpyxl ...`.
- `gcloud` is logged in as the project owner, project `prudential-poc-484904`.
- The `docker` CLI is installed, but no Docker daemon runs in WSL. Cloud Build builds the image at
  deploy time.
- ADK Web runs on port 8000 (started by the user). Run verification servers on port 8001 with
  `--session_service_uri memory://`. Follow the `pkill` rules in CLAUDE.md.
- `gh` is not installed; git in WSL has no credential helper. The user pushes from their own
  terminal.
- Secrets live in the git-ignored `.env` and the service-account JSON. Never print or copy them. The
  `.env` Chatwoot token and secret belong to the live agent bot. The test prompts use fictional
  identity data only.

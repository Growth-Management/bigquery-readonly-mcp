# BigQuery Readonly MCP

BigQuery Readonly MCP is a FastAPI-based Custom MCP server for safely querying BigQuery from ChatGPT. It is designed as a reusable internal analytics MCP: each tool accepts `project_id`. The initial validation project was `ice-sh`; the current pilot default project is `ice-mp`.

## Scope

- GitHub repository: `Growth-Management/bigquery-readonly-mcp`
- Cloud Run deploy project: `ice-sh`
- Initial BigQuery validation project: `ice-sh`
- Current pilot default BigQuery project: `ice-mp`
- Initial pilot user: `sinohara@impress.co.jp`
- Allowed email domain: `impress.co.jp`
- Allowed project IDs: empty for the current pilot, so the approved user may specify any project readable through their own BigQuery IAM
- Allowed dataset IDs: empty by default, so BigQuery IAM controls dataset access
- Default `maximumBytesBilled`: 1GB
- Default `max_results`: 1000
- Default query timeout: 60 seconds
- Current session backend: Firestore persistence enabled, refresh-token backed access-token renewal enabled, with `SESSION_TTL_SECONDS=86400`

## Security Model

The MCP server uses Google OAuth and BigQuery calls run with the authenticated user's access token. It does not use a service account to impersonate users for BigQuery query execution.

Users should receive the minimum required IAM permissions:

- `roles/bigquery.jobUser` on the project where jobs are created
- `roles/bigquery.dataViewer` on only the datasets they may inspect

The server enforces readonly SQL before execution. `run_readonly_query` and `dry_run_query` only allow one `SELECT` or `WITH` statement and reject DML, DDL, `EXPORT`, `LOAD`, grants, revokes, and procedure calls.

The server can also enforce application-side allowlists:

- `ALLOWED_PROJECT_IDS`: when set, tool calls for projects outside the list are rejected before any BigQuery API call is made. When empty, project access is governed by the logged-in user's BigQuery IAM.
- `ALLOWED_DATASET_IDS`: when set, `list_datasets` is filtered and `list_tables` / `get_table_schema` calls outside the list are rejected before any BigQuery API call is made.
- `ALLOWED_USER_EMAILS`: when set, tool calls from users outside the list are rejected before any BigQuery API call is made.

Allowlist rejections are recorded in audit logs with `success=false` and a `rejection_reason`.

## MCP Tools

- `list_projects`
- `list_datasets`
- `list_tables`
- `get_table_schema`
- `dry_run_query`
- `run_readonly_query`

All tools accept `project_id` where applicable. If omitted, the current pilot default is `ice-mp`.

## Endpoints

- `GET /healthz`
- `GET /health`
- `POST /mcp`
- `GET /oauth/authorize`
- `GET /oauth/callback`
- `POST /oauth/token`
- `GET /.well-known/oauth-authorization-server`

Use `/health` for Cloud Run external health checks. Cloud Run can reserve `/healthz` before requests reach the container, causing Google Frontend 404 responses even when the FastAPI app is healthy.

## Local Development

Create a local environment and install dependencies:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Set local environment variables. Do not commit real secrets. Local development may use `memory`; the pilot deployment uses Firestore.

```bash
export BASE_URL="http://localhost:8080"
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export SESSION_SECRET="replace-with-random-value"
export ALLOWED_DOMAIN="impress.co.jp"
export DEFAULT_PROJECT_ID="ice-mp"
export ALLOWED_PROJECT_IDS=""
export ALLOWED_DATASET_IDS=""
export ALLOWED_USER_EMAILS="sinohara@impress.co.jp"
export MAXIMUM_BYTES_BILLED="1073741824"
export MAX_RESULTS="1000"
export QUERY_TIMEOUT_SECONDS="60"
export SESSION_TTL_SECONDS="86400"
export OAUTH_REFRESH_WINDOW_SECONDS="300"
export SESSION_STORE_BACKEND="memory"
export FIRESTORE_SESSION_COLLECTION="bigquery_mcp_sessions"
```

`ALLOWED_DATASET_IDS` is a comma-separated list of `project_id:dataset_id` values, for example:

```bash
export ALLOWED_DATASET_IDS="ice-mp:example_datamart,ice-mp:example_source"
```

Run the app:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload
```

Run tests:

```bash
pytest
```

## OAuth Setup

Configure a Google OAuth Web application in `ice-sh`:

- Consent screen: internal or equivalent organization-limited configuration
- Authorized domain: `impress.co.jp`
- Redirect URI: `https://<cloud-run-url>/oauth/callback`
- Scopes:
  - `openid`
  - `email`
  - `profile`
  - `https://www.googleapis.com/auth/bigquery.readonly`

Store these values in Secret Manager rather than the repository:

- `google-oauth-client-id`
- `google-oauth-client-secret`
- `bigquery-mcp-session-secret`

For MCP clients such as ChatGPT custom connectors, this service acts as the OAuth server and bridges to Google OAuth internally:

- Authorization endpoint: `https://<cloud-run-url>/oauth/authorize`
- Token endpoint: `https://<cloud-run-url>/oauth/token`
- Metadata endpoint: `https://<cloud-run-url>/.well-known/oauth-authorization-server`
- MCP endpoint: `https://<cloud-run-url>/mcp`

The OAuth callback `/oauth/callback` is the Google OAuth redirect URI. MCP clients should be configured with their own callback URL in the client UI when prompted; the service preserves that callback through the OAuth state and returns an authorization code to the MCP client.

The service requests Google OAuth with `access_type=offline`, `include_granted_scopes=true`, and consent/account selection prompts so a refresh token can be captured for Firestore-backed sessions. If Google does not return a refresh token for an existing grant, revoke the app grant from the user's Google account or reconnect with an explicit consent flow, then retry the MCP connection.

## Session Storage

The current pilot deployment uses Firestore-backed session storage with refresh-token backed access-token renewal:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=86400
OAUTH_REFRESH_WINDOW_SECONDS=300
```

Firestore persistence keeps a post-login MCP session available across Cloud Run instance restarts, scale-out, and new revisions. This was initially validated on 2026-06-08: a session document was created in Firestore, the access token was stored only as encrypted ciphertext, and the same `mcp_session` cookie continued to work after new Cloud Run revisions and GitHub Actions deploys.

As of 2026-06-15, newly created Firestore sessions can also store a Google refresh token as encrypted ciphertext. When a stored access token is within `OAUTH_REFRESH_WINDOW_SECONDS` of expiry, the server exchanges the refresh token for a new access token and updates the Firestore document. This makes the MCP session TTL independent from the roughly 1-hour Google access-token lifetime, while keeping BigQuery calls bound to the logged-in user's IAM.

Security behavior:

- Access tokens and refresh tokens are encrypted before being stored in Firestore.
- Encryption uses AES-GCM with a key derived from `SESSION_SECRET`.
- Refresh-token ciphertext is bound to both the session id and token purpose.
- `SESSION_SECRET` rotation intentionally invalidates existing persisted sessions.
- Invalid, expired, or undecryptable session documents are deleted and treated as logged out.
- If Google rejects a refresh-token exchange, the session is treated as logged out and the user must reconnect.
- Firestore persistence does not grant BigQuery access. BigQuery calls still use the logged-in user's OAuth token and IAM permissions.

Operational notes:

- Existing sessions created before refresh-token support may still expire at the previous access-token boundary. Reconnect once after deployment so the new session stores a refresh token.
- The pilot `SESSION_TTL_SECONDS` is 24 hours. Increase only after confirming risk acceptance for refresh-token storage and session revocation behavior.
- Short-lived OAuth authorization requests and authorization codes remain in memory, so a login flow that overlaps a revision restart may still need to be retried. This does not affect already-created Firestore MCP sessions.

## Cloud Run Deployment

The GitHub Actions workflow expects these GitHub Secrets:

- `GCP_PROJECT_ID`: `ice-sh`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `BASE_URL`: deployed Cloud Run URL or custom domain

The deploy service account needs only deployment permissions, such as Artifact Registry write and Cloud Run deploy permissions. It is not used for BigQuery query execution.

Current pilot deployment settings:

- `DEFAULT_PROJECT_ID=ice-mp`
- `ALLOWED_PROJECT_IDS=`
- `ALLOWED_DATASET_IDS=`
- `ALLOWED_USER_EMAILS=sinohara@impress.co.jp`
- `MAXIMUM_BYTES_BILLED=1073741824`
- `MAX_RESULTS=1000`
- `QUERY_TIMEOUT_SECONDS=60`
- `SESSION_STORE_BACKEND=firestore`
- `FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions`
- `SESSION_TTL_SECONDS=86400`
- `OAUTH_REFRESH_WINDOW_SECONDS=300`

Deployment is managed per GCP project. The Cloud Run deployment project is `ice-sh`; the current default BigQuery project is `ice-mp`, but project access is governed by the logged-in user's BigQuery IAM because `ALLOWED_PROJECT_IDS` is empty.

See [`docs/cloud-run.md`](docs/cloud-run.md) for the full Phase 5 deployment procedure, including required APIs, Artifact Registry, Secret Manager, manual deploy, `/health`, Cloud Run session storage, and Cloud Logging checks.

See [`docs/github-actions-deploy.md`](docs/github-actions-deploy.md) for the preferred GitHub Actions deployment path using Workload Identity Federation.

See [`docs/phase-7-ice-sh-validation.md`](docs/phase-7-ice-sh-validation.md) for the Phase 7 validation record.

See [`docs/rollout-policy.md`](docs/rollout-policy.md) for the Phase 8 rollout policy covering rollout patterns, allowlists, per-project deployment ownership, validation, audit retention, session persistence, and follow-up hardening.

See [`docs/all-project-iam-user-pilot.md`](docs/all-project-iam-user-pilot.md) for the approved pilot change that leaves project access to the named user's BigQuery IAM while keeping `ALLOWED_USER_EMAILS=sinohara@impress.co.jp`.

See [`docs/session-refresh-validation.md`](docs/session-refresh-validation.md) for the refresh-token session validation plan and Cloud Shell checks.

## Initial Validation On ice-sh

Use a user account in the allowed domain with the required BigQuery IAM permissions, then verify:

- MCP connects to `/mcp`
- Google OAuth login succeeds
- dataset list can be retrieved from `ice-sh`
- table list can be retrieved
- schema can be retrieved
- dry run returns estimated bytes processed
- `SELECT` executes within limits
- DML and DDL are rejected before BigQuery execution
- unauthorized projects return Access Denied
- audit logs are emitted to Cloud Logging

Current status as of 2026-06-04: Phase 7 validation is complete. `ice-sh` readonly checks, SQL guard checks, Cloud Logging audit checks, and unauthorized-project rejection have been verified. The unauthorized-project check used `bq-mcp-access-denied-test-2` with a project-level IAM Deny policy for `sinohara@impress.co.jp`; MCP `dry_run_query` returned HTTP `403 Forbidden`.

## Current Pilot

Current status as of 2026-06-15: pilot operation is enabled for `sinohara@impress.co.jp` only. `ALLOWED_PROJECT_IDS` is empty after security-owner approval, so the named user may use any BigQuery project readable through their own Google account IAM. `DEFAULT_PROJECT_ID=ice-mp` keeps ordinary use oriented to the pilot project. `ALLOWED_DATASET_IDS` is empty, so dataset access is governed by the logged-in user's BigQuery IAM. Firestore-backed MCP session persistence is enabled with refresh-token renewal and `SESSION_TTL_SECONDS=86400`.

Before expanding beyond the initial pilot user, repeat the rollout checklist in `docs/rollout-policy.md` and decide whether `ALLOWED_PROJECT_IDS`, `ALLOWED_DATASET_IDS`, or additional named-user restrictions are needed.

## Audit Logging

Every tool call writes a single-line JSON audit event to stdout. Cloud Run ingests stdout into Cloud Logging, where the `message`, `event_type`, `severity`, and tool-specific fields can be filtered.

Cloud Logging is the required audit source. BigQuery audit dataset export has been evaluated as an optional Phase 8 P2 hardening path, recommended through a Cloud Logging Log Router sink when retention, reporting, or dashboard requirements justify it. Query history UI is deferred until exported audit data and administrator review requirements are confirmed.

Each audit event includes:

- `severity`
- `message`
- `timestamp`
- `event_type`
- `user_email`
- `tool`
- `project_id`
- `dataset`
- `table`
- `bytes_processed`
- `success`
- `error`
- `rejection_reason` for failed or rejected calls

`rejection_reason` uses these categories:

- `project_not_allowed`: `project_id` is outside `ALLOWED_PROJECT_IDS`.
- `dataset_not_allowed`: `project_id:dataset_id` is outside `ALLOWED_DATASET_IDS` for dataset-targeting metadata tools.
- `user_not_allowed`: user email is outside `ALLOWED_USER_EMAILS`.
- `sql_not_allowed`: SQL guard rejected a non-readonly or unsafe query.
- `bigquery_iam_denied`: BigQuery returned a permission-denied response, including HTTP 403.
- `bigquery_api_error`: BigQuery or HTTP API failed for a non-403 API reason.
- `execution_error`: internal execution failed outside the known categories.

Some fields may be empty when the tool does not target a dataset or table, or when validation fails before a BigQuery job is created.

Example Cloud Logging filter:

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.project_id="ice-mp"
```

To inspect rejected calls by category:

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.success=false
jsonPayload.rejection_reason="project_not_allowed"
```

## Current Phase Coverage

- Phase 1: FastAPI app, `/healthz`, `/health`, `/mcp`, OAuth authorize/callback skeleton, user email lookup
- Phase 2: six initial BigQuery tools
- Phase 3: readonly SQL guard, `maximumBytesBilled`, `max_results`, timeout, basic query error handling
- Phase 4: structured JSON audit logs are emitted to stdout for Cloud Logging ingestion
- Phase 5: Docker, env example, Secret Manager policy, Cloud Run deployment procedure, `/health` verification, and Firestore-backed session storage are complete for `ice-sh`
- Phase 6: GitHub Actions workflow, Workload Identity Federation, IAM, GitHub Secrets, deploy verification, and Firestore session env pinning are complete
- Phase 7: `ice-sh` OAuth, MCP, BigQuery tools, readonly guard, unauthorized-project rejection, and audit log validation are complete
- Phase 8: `ALLOWED_PROJECT_IDS`, `ALLOWED_DATASET_IDS`, `ALLOWED_USER_EMAILS`, structured audit rejection categories, allow/reject tests, current pilot defaults, Firestore-backed session persistence, and refresh-token backed session renewal are implemented; project access is currently user-IAM-scoped for `sinohara@impress.co.jp`; BigQuery audit dataset export and query history UI are evaluated; rollout patterns, allowlist policy, per-project rollout record template, per-project validation, audit requirements, session policy, and follow-up backlog are documented in `docs/rollout-policy.md`

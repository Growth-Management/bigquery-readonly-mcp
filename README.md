# BigQuery Readonly MCP

BigQuery Readonly MCP is a FastAPI-based Custom MCP server for safely querying BigQuery from ChatGPT. It is designed as a reusable internal analytics MCP: each tool accepts `project_id`, while the initial validation project is `ice-sh`.

## Scope

- GitHub repository: `Growth-Management/bigquery-readonly-mcp`
- Cloud Run deploy project: `ice-sh`
- Initial BigQuery validation project: `ice-sh`
- Allowed email domain: `impress.co.jp`
- Default `maximumBytesBilled`: 1GB
- Default `max_results`: 1000
- Default query timeout: 60 seconds

## Security Model

The MCP server uses Google OAuth and BigQuery calls run with the authenticated user's access token. It does not use a service account to impersonate users for BigQuery query execution.

Users should receive the minimum required IAM permissions:

- `roles/bigquery.jobUser` on the project where jobs are created
- `roles/bigquery.dataViewer` on only the datasets they may inspect

The server enforces readonly SQL before execution. `run_readonly_query` and `dry_run_query` only allow one `SELECT` or `WITH` statement and reject DML, DDL, `EXPORT`, `LOAD`, grants, revokes, and procedure calls.

## MCP Tools

- `list_projects`
- `list_datasets`
- `list_tables`
- `get_table_schema`
- `dry_run_query`
- `run_readonly_query`

All tools accept `project_id` where applicable. If omitted, the default is `ice-sh`.

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

Set local environment variables. Do not commit real secrets.

```bash
export BASE_URL="http://localhost:8080"
export GOOGLE_OAUTH_CLIENT_ID="..."
export GOOGLE_OAUTH_CLIENT_SECRET="..."
export SESSION_SECRET="replace-with-random-value"
export ALLOWED_DOMAIN="impress.co.jp"
export DEFAULT_PROJECT_ID="ice-sh"
export MAXIMUM_BYTES_BILLED="1073741824"
export MAX_RESULTS="1000"
export QUERY_TIMEOUT_SECONDS="60"
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

## Cloud Run Deployment

The GitHub Actions workflow expects these GitHub Secrets:

- `GCP_PROJECT_ID`: `ice-sh`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `BASE_URL`: deployed Cloud Run URL or custom domain

The deploy service account needs only deployment permissions, such as Artifact Registry write and Cloud Run deploy permissions. It is not used for BigQuery query execution.

Deployment is managed per GCP project. The initial deployment target is `ice-sh`; when this MCP is rolled out to another project, create that project's own Cloud Run service, Artifact Registry repository, Secret Manager secrets, Workload Identity Federation bindings, and GitHub Secrets.

See [`docs/cloud-run.md`](docs/cloud-run.md) for the full Phase 5 deployment procedure, including required APIs, Artifact Registry, Secret Manager, manual deploy, `/health`, and Cloud Logging checks.

See [`docs/github-actions-deploy.md`](docs/github-actions-deploy.md) for the preferred GitHub Actions deployment path using Workload Identity Federation.

See [`docs/phase-7-ice-sh-validation.md`](docs/phase-7-ice-sh-validation.md) for the current Phase 7 validation record.

See [`docs/rollout-policy.md`](docs/rollout-policy.md) for the Phase 8 rollout policy covering allowlists, per-project deployment ownership, audit retention, and follow-up hardening.

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

Current status as of 2026-06-01: all listed `ice-sh` readonly and audit checks are verified except the unauthorized-project Access Denied case. A non-accessible project returned a JSON-RPC error, but the observed BigQuery response was `404 Project not found`, not `403 Access Denied`. Keep the Access Denied case open until an existing project outside the user's IAM scope is available for validation.

## Audit Logging

Every tool call writes a single-line JSON audit event to stdout. Cloud Run ingests stdout into Cloud Logging, where the `message`, `event_type`, `severity`, and tool-specific fields can be filtered.

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

Some fields may be empty when the tool does not target a dataset or table, or when validation fails before a BigQuery job is created.

Example Cloud Logging filter:

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.project_id="ice-sh"
```

## Current Phase Coverage

- Phase 1: FastAPI app, `/healthz`, `/health`, `/mcp`, OAuth authorize/callback skeleton, user email lookup
- Phase 2: six initial BigQuery tools
- Phase 3: readonly SQL guard, `maximumBytesBilled`, `max_results`, timeout, basic query error handling
- Phase 4: structured JSON audit logs are emitted to stdout for Cloud Logging ingestion
- Phase 5: Docker, env example, Secret Manager policy, Cloud Run deployment procedure, and `/health` verification are complete for `ice-sh`
- Phase 6: GitHub Actions workflow, Workload Identity Federation, IAM, GitHub Secrets, and deploy verification are complete for `ice-sh`
- Phase 7: `ice-sh` OAuth, MCP, BigQuery tool, readonly guard, and audit log validation are verified; unauthorized-project Access Denied validation remains open until a real project without user access is available
- Phase 8: rollout policy is documented in `docs/rollout-policy.md`

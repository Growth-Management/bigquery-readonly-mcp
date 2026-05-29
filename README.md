# BigQuery Readonly MCP

BigQuery Readonly MCP is a FastAPI-based Custom MCP server for safely querying BigQuery from ChatGPT. It is designed as a reusable internal analytics MCP: each tool accepts `project_id`, while the initial validation project is `ice-sh`.

## Scope

- GitHub repository: `Growth-Management/bigquery-readonly-mcp`
- Cloud Run deploy project: `bigquery-mcp-prod`
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
- `POST /mcp`
- `GET /oauth/authorize`
- `GET /oauth/callback`
- `GET /.well-known/oauth-authorization-server`

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

Configure a Google OAuth Web application in `bigquery-mcp-prod`:

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

## Cloud Run Deployment

The GitHub Actions workflow expects these GitHub Secrets:

- `GCP_PROJECT_ID`: `bigquery-mcp-prod`
- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `BASE_URL`: deployed Cloud Run URL or custom domain

The deploy service account needs only deployment permissions, such as Artifact Registry write and Cloud Run deploy permissions. It is not used for BigQuery query execution.

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

## Audit Logging

Every tool call logs a structured audit event with:

- `timestamp`
- `user_email`
- `tool`
- `project_id`
- `dataset`
- `table`
- `bytes_processed`
- `success`
- `error`

Some fields may be empty when the tool does not target a dataset or table, or when validation fails before a BigQuery job is created.

## Current Phase Coverage

- Phase 1: FastAPI app, `/healthz`, `/mcp`, OAuth authorize/callback skeleton, user email lookup
- Phase 2: six initial BigQuery tools
- Phase 3: readonly SQL guard, `maximumBytesBilled`, `max_results`, timeout, basic query error handling
- Phase 4 preview: structured audit log helper is included, but production log filtering and retention policy still need validation

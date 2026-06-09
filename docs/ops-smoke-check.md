# Ops Smoke Check

This document describes the issue-triggered GitHub Actions workflow for read-only operational checks.

Workflow file:

```text
.github/workflows/ops-smoke-check.yml
```

## Purpose

The ops smoke check lets the agent trigger Cloud Run and audit-log checks through the existing GitHub integration by creating a GitHub issue.

It does not use `MCP_SESSION` cookies and does not execute BigQuery as a logged-in user. User OAuth smoke tests still require the user or a dedicated validation account.

## Current Status

Validated on 2026-06-09 for the current `ice-mp` pilot.

Validation evidence:

- Issue: <https://github.com/Growth-Management/bigquery-readonly-mcp/issues/3>
- Run: <https://github.com/Growth-Management/bigquery-readonly-mcp/actions/runs/27174332835>
- Successful result comment: <https://github.com/Growth-Management/bigquery-readonly-mcp/issues/3#issuecomment-4654651366>

Validated checks:

- `GET /health` returned `{"status":"ok"}`.
- Cloud Run environment matched the current `ice-mp` pilot values.
- Cloud Logging `bigquery_mcp_tool_call` audit records were readable.
- Firestore session collection was readable.
- Firestore returned expected session document field names only: `access_token_ciphertext`, `email`, `expires_at`, and `nonce`.

The validation confirmed that the agent can trigger the workflow by creating a GitHub issue and recover the result from the workflow's issue comment.

## Trigger

Open a GitHub issue whose title starts with exactly:

```text
[bigquery-mcp-ops] smoke check
```

Only `issues.opened` events with that title prefix run the job. Other issues are ignored by the job condition.

Suggested issue title:

```text
[bigquery-mcp-ops] smoke check ice-mp pilot
```

Suggested issue body:

```markdown
Run read-only ops smoke checks for the current `ice-mp` pilot.

Expected values:
- Cloud Run deploy project: `ice-sh`
- Cloud Run service: `bigquery-readonly-mcp`
- Region: `asia-northeast1`
- `DEFAULT_PROJECT_ID=ice-mp`
- `ALLOWED_PROJECT_IDS=ice-mp`
- `ALLOWED_USER_EMAILS=sinohara@impress.co.jp`
- `SESSION_STORE_BACKEND=firestore`
- `SESSION_TTL_SECONDS=3600`
```

## Checks Performed

The workflow checks:

1. `GET /health` returns `{"status":"ok"}`.
2. Cloud Run has the expected pilot environment values.
3. Recent `bigquery_mcp_tool_call` audit logs are readable from Cloud Logging.
4. Firestore session collection can be read and exposes only expected document field names in logs.

Expected Cloud Run values:

| Variable | Expected value |
| --- | --- |
| `DEFAULT_PROJECT_ID` | `ice-mp` |
| `ALLOWED_PROJECT_IDS` | `ice-mp` |
| `ALLOWED_DATASET_IDS` | empty |
| `ALLOWED_USER_EMAILS` | `sinohara@impress.co.jp` |
| `SESSION_STORE_BACKEND` | `firestore` |
| `FIRESTORE_SESSION_COLLECTION` | `bigquery_mcp_sessions` |
| `SESSION_TTL_SECONDS` | `3600` |

## Required GitHub Secrets

The workflow reuses the existing deployment secrets:

| Secret | Purpose |
| --- | --- |
| `GCP_PROJECT_ID` | Cloud Run / Logging / Firestore project. Current value: `ice-sh`. |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Workload Identity Federation provider. |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Service account impersonated by GitHub Actions. |
| `BASE_URL` | Cloud Run base URL. |

## Required GCP IAM

The GitHub Actions service account must be able to perform read-only operational checks.

Minimum expected permissions:

| Check | Required capability |
| --- | --- |
| Cloud Run service describe | Cloud Run viewer/admin capability, e.g. existing deploy role or `roles/run.viewer`. |
| Cloud Logging read | `roles/logging.viewer`. |
| Firestore document list | Firestore/Datastore read capability, e.g. `roles/datastore.viewer`. |

The current deployment required these read-only grants on `ice-sh`:

- `github-actions-bigquery-mcp@ice-sh.iam.gserviceaccount.com`: `roles/logging.viewer`, `roles/datastore.viewer`.
- `ice-deployer@ice-sh.iam.gserviceaccount.com`: `roles/logging.viewer`, `roles/datastore.viewer`.

The workflow initially failed on Cloud Logging until `roles/logging.viewer` was granted, then failed on Firestore until `roles/datastore.viewer` was granted to the actual deployment identity. Keep both identities aligned unless `GCP_DEPLOY_SERVICE_ACCOUNT` is confirmed and the unused identity is retired.

## Safety Boundary

This workflow must remain read-only:

- Do not pass `MCP_SESSION` into GitHub Actions.
- Do not store user OAuth cookies or access tokens in GitHub Secrets.
- Do not run MCP tool calls as a logged-in user from this workflow.
- Do not grant the GitHub Actions service account BigQuery data access for user query execution.

## Result Interpretation

Successful run means:

- Cloud Run is alive.
- The deployed environment matches the current `ice-mp` pilot values.
- Cloud Logging audit records are readable.
- Firestore session collection is reachable.

It does not prove:

- Google OAuth login succeeds for a user.
- A user can run `list_datasets` through MCP.
- BigQuery IAM is correct for a user.

Those still require a user-side MCP smoke test or a dedicated validation account.

## Rollback

To disable this trigger, remove `.github/workflows/ops-smoke-check.yml` or change the title prefix condition.

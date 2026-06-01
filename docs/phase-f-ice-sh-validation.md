# Phase F: ice-sh Revalidation

Date: 2026-06-01
Target PR: https://github.com/Growth-Management/bigquery-readonly-mcp/pull/1
Branch: `codex/oauth-persistence-foundation`
Head checked: `64417c23667b294ac86cf3a2cfc0f3e1600c4f43`
Cloud Run service under test: `https://bigquery-readonly-mcp-ppwdcgrska-an.a.run.app`
Initial validation project: `ice-sh`

## Purpose

Phase F verifies that the OAuth persistence improvements fix the short-lived authentication problem and that the Phase 7 BigQuery readonly checks still pass after Cloud Run restart, elapsed time, and ChatGPT reconnect.

## Current Deployment Status

PR #1 is still open and has not been merged to `main`.

The workflow now runs on pull requests to `main`. For commit `64417c23667b294ac86cf3a2cfc0f3e1600c4f43`, GitHub Actions run `26739510228` completed the `test` job successfully and skipped `deploy` as intended for a pull request.

Because deploy is intentionally skipped for PR events, the current Cloud Run service is still treated as the pre-persistence deployment for Phase F purposes. The persistence implementation should be deployed by merging to `main` or running `workflow_dispatch` after confirming runtime secrets and IAM.

## Validation Results

| Check | Result | Evidence / Notes |
| --- | --- | --- |
| PR mergeability | PASS | PR #1 is mergeable. |
| PR CI route | PASS | GitHub Actions run `26739510228`: `test` succeeded. |
| PR deploy skip behavior | PASS | GitHub Actions run `26739510228`: `deploy` skipped for PR as intended. |
| PR deployed to Cloud Run | BLOCKED | PR deploy is intentionally skipped. Deployment of the persistence implementation was not confirmed. |
| MCP connection through ChatGPT connector | FAIL | `list_projects(project_id="ice-sh")` returned HTTP 401 from `/mcp`. |
| OAuth persistence symptom check | FAIL | The error was `Login required at /oauth/authorize`, which is the short-lived auth failure Phase F is meant to eliminate. |
| Cloud Run direct `/health` check from workspace | BLOCKED | Workspace network proxy returned `CONNECT tunnel failed, response 403`; this does not prove Cloud Run health failure. |
| `ice-sh` dataset list | BLOCKED | Could not proceed because MCP session resolution returned 401. |
| table list | BLOCKED | Blocked by MCP 401. |
| schema fetch | BLOCKED | Blocked by MCP 401. |
| dry run | BLOCKED | Blocked by MCP 401. |
| SELECT query | BLOCKED | Blocked by MCP 401. |
| DML / DDL rejection | BLOCKED | Blocked by MCP 401 before SQL validation. |
| unauthorized project rejection | BLOCKED | Blocked by MCP 401 before BigQuery authorization check. |
| audit log confirmation | BLOCKED | Requires Cloud Logging access or deployed validation run output. |
| Firestore TTL configuration | NOT RUN | Requires GCP project access. Procedure is documented in `docs/oauth-persistence.md`. |
| KMS rotation configuration | NOT RUN | Requires GCP project access. Procedure is documented in `docs/oauth-persistence.md`. |
| token lifecycle review | NOT RUN | Requires deployed persistence records. Procedure is documented in `docs/oauth-persistence.md`. |

## Connector Error Evidence

A ChatGPT connector call to `list_projects` with `project_id="ice-sh"` returned:

```text
McpServerError: Login required at /oauth/authorize
HTTP status: 401
URL: https://bigquery-readonly-mcp-ppwdcgrska-an.a.run.app/mcp
```

This is useful Phase F evidence: the current deployed service still exhibits the authentication symptom that the OAuth persistence PR is intended to fix.

## CI / Deploy Route Findings

The workflow route is now:

- `pull_request` to `main`: run tests only; never deploy.
- `push` to `main`: run tests, then deploy.
- `workflow_dispatch`: run tests, then deploy.

The deploy command now passes OAuth persistence settings to Cloud Run, including Firestore collection names, OAuth state/code TTLs, session TTL, `FIRESTORE_PROJECT_ID`, `KMS_KEY_NAME`, and `TOKEN_HASH_SECRET` via Secret Manager.

## Conclusion

Phase F was started, but it cannot be completed against the current deployed service.

The current result is **BLOCKED before BigQuery tool validation** because the service returned 401 during MCP session resolution. The PR CI route is now confirmed healthy, but deployment is intentionally pending until `main` merge or manual dispatch.

## Required Next Steps

1. Confirm Secret Manager has `bigquery-mcp-token-hash-secret`.
2. Confirm runtime service account has:
   - Secret Manager access for `bigquery-mcp-token-hash-secret`.
   - Firestore read/write for persistence collections.
   - `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the OAuth token KMS key.
3. Merge PR #1 or run `workflow_dispatch` for `codex/oauth-persistence-foundation` if branch validation deployment is desired.
4. Configure Firestore TTL for `oauth_auth_requests`, `oauth_authorization_codes`, and `mcp_sessions`.
5. Re-run Phase F checks:
   - OAuth login.
   - `ice-sh` dataset list.
   - table list.
   - schema fetch.
   - dry run.
   - SELECT execution.
   - DML / DDL rejection.
   - unauthorized project rejection.
   - audit log confirmation.
   - elapsed-time reconnect check.
   - Cloud Run restart or new instance reconnect check.

## Security Notes

- Do not bypass OAuth to complete Phase F.
- Do not use a service account to impersonate users for BigQuery execution.
- Keep BigQuery execution tied to the authenticated user's OAuth token and IAM permissions.
- Treat the 401 result as a valid failure signal, not as a reason to weaken authentication.

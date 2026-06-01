# Phase F: ice-sh Revalidation

Date: 2026-06-01
Target PR: https://github.com/Growth-Management/bigquery-readonly-mcp/pull/1
Branch: `codex/oauth-persistence-foundation`
Head checked: `d416655d18f10be3c822596bb521a45a16810605`
Cloud Run service under test: `https://bigquery-readonly-mcp-ppwdcgrska-an.a.run.app`
Initial validation project: `ice-sh`

## Purpose

Phase F verifies that the OAuth persistence improvements fix the short-lived authentication problem and that the Phase 7 BigQuery readonly checks still pass after Cloud Run restart, elapsed time, and ChatGPT reconnect.

## Current Deployment Status

PR #1 is still open and has not been merged to `main`.

No GitHub Actions workflow run was found for commit `d416655d18f10be3c822596bb521a45a16810605` at the time of this validation attempt. Because the OAuth persistence branch has not been observed as deployed, the current Cloud Run service is treated as the pre-persistence deployment for Phase F purposes.

## Validation Results

| Check | Result | Evidence / Notes |
| --- | --- | --- |
| PR mergeability | PASS | PR #1 is mergeable. |
| PR deployed to Cloud Run | BLOCKED | No workflow run was found for the latest PR head commit. Deployment of the persistence implementation was not confirmed. |
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

## Conclusion

Phase F was started, but it cannot be completed against the current deployed service.

The current result is **BLOCKED before BigQuery tool validation** because the service returned 401 during MCP session resolution. The next meaningful Phase F attempt should happen after the OAuth persistence PR is merged and deployed, or after the branch is deployed to a dedicated validation Cloud Run service.

## Required Next Steps

1. Run CI for PR #1 or confirm why the branch does not trigger a workflow.
2. Merge PR #1 or deploy `codex/oauth-persistence-foundation` to a validation Cloud Run service.
3. Confirm these runtime settings are present on Cloud Run:
   - `TOKEN_HASH_SECRET`
   - `FIRESTORE_PROJECT_ID`
   - `OAUTH_TOKEN_COLLECTION`
   - `OAUTH_AUTH_REQUEST_COLLECTION`
   - `OAUTH_AUTHORIZATION_CODE_COLLECTION`
   - `MCP_SESSION_COLLECTION`
   - `OAUTH_STATE_TTL_SECONDS`
   - `OAUTH_CODE_TTL_SECONDS`
   - `KMS_KEY_NAME`
4. Confirm runtime service account IAM:
   - Firestore read/write for persistence collections.
   - `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the OAuth token KMS key.
   - Secret Manager access only for service-level secrets.
5. Configure Firestore TTL for `oauth_auth_requests`, `oauth_authorization_codes`, and `mcp_sessions`.
6. Re-run Phase F checks:
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

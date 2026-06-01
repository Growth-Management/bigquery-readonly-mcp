# Rollout Policy

This document captures the Phase 8 rollout policy for expanding `bigquery-readonly-mcp` beyond the initial `ice-sh` validation.

## Principles

- Keep BigQuery execution tied to the logged-in Google user.
- Do not use a service account to proxy BigQuery queries for all users.
- Keep SQL readonly: allow only `SELECT` and `WITH` queries.
- Manage deployment resources per GCP project.
- Prefer IAM and dataset-level permissions over broad application-side bypasses.
- Keep every rollout auditable in Cloud Logging.

## Initial Rollout Decisions

| Area | Phase 8 decision | Reason |
| --- | --- | --- |
| Project allowlist | Required as an operational policy per rollout. Each Cloud Run deployment has one intended default project and must document any additional allowed projects. | Prevents accidental cross-project use while preserving the generic `project_id` tool design. |
| Dataset allowlist | Use BigQuery IAM first. Grant `roles/bigquery.dataViewer` at dataset scope wherever possible. | Dataset-level IAM is the source of truth and avoids duplicating access policy in the MCP service. |
| User allowlist | Use Google OAuth domain allowlist plus BigQuery IAM for initial operation. | Keeps onboarding simple while still requiring the user's own Google identity and IAM permissions. |
| Domain allowlist | Required. Initial value: `impress.co.jp`. | Blocks non-company Google accounts before BigQuery access is attempted. |
| Per-project policy | Required. Cloud Run, Artifact Registry, Secret Manager, WIF, deploy service account, GitHub Secrets, OAuth redirect URI, and health check must be managed per GCP project. | Keeps blast radius and deployment ownership clear. |
| BigQuery audit dataset | Follow-up hardening, not required for initial operation. Cloud Logging is required now. | Cloud Logging satisfies Phase 7 audit verification; BigQuery persistence can be added once retention/reporting requirements are clear. |
| Query history UI | Follow-up improvement, not required for initial operation. | Audit logs are enough for the initial controlled rollout. |

## Per-Project Rollout Checklist

For every new project, create or confirm the following:

1. GCP APIs are enabled: Cloud Run, Artifact Registry, Secret Manager, IAM Credentials, and Cloud Build if using manual builds.
2. Artifact Registry repository exists in the target region.
3. OAuth Web application has the Cloud Run callback URL registered.
4. Secret Manager contains `google-oauth-client-id`, `google-oauth-client-secret`, and `bigquery-mcp-session-secret`.
5. Runtime service account can read only the required secrets.
6. Deploy service account has deployment permissions only.
7. Workload Identity Federation binding is restricted to `Growth-Management/bigquery-readonly-mcp`.
8. GitHub Secrets are set for that deployment target: `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_DEPLOY_SERVICE_ACCOUNT`, and `BASE_URL`.
9. Cloud Run environment variables are set for the target project, domain, and limits.
10. OAuth redirect URI and `BASE_URL` match exactly.
11. External health check uses `/health`, not `/healthz`.
12. Phase 7 validation is repeated for the target project before opening use to more users.

## BigQuery IAM Policy

Grant users only the permissions they need:

- `roles/bigquery.jobUser` on the project where query jobs run.
- `roles/bigquery.dataViewer` on the smallest practical dataset scope.

Avoid project-wide `dataViewer` unless the project is explicitly intended for broad analysis access.

## Audit Requirements

Every rollout must confirm Cloud Logging receives structured audit records with:

- `event_type="bigquery_mcp_tool_call"`
- `user_email`
- `tool`
- `project_id`
- `dataset`
- `table`
- `bytes_processed`
- `success`
- `error`

Initial retention stays in Cloud Logging. A BigQuery audit dataset can be added later if longer retention, reporting, or dashboarding is required.

## Follow-Up Hardening Candidates

These are not required to complete the initial `ice-sh` rollout, but should be considered before broad multi-project use:

- Environment-level `ALLOWED_PROJECT_IDS` enforcement.
- Optional `ALLOWED_USER_EMAILS` for sensitive deployments.
- Optional dataset allowlist for deployments where IAM alone is not enough for operational policy.
- BigQuery audit dataset export.
- Query history UI for administrators.
- Dedicated runtime service account instead of the default compute service account.

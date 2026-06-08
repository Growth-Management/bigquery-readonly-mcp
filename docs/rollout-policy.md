# Rollout Policy

This document captures the Phase 8 rollout policy for expanding `bigquery-readonly-mcp` beyond the initial `ice-sh` validation.

## Phase 8 Status

Phase 8 is ready for controlled rollout after Phase 7 completed on 2026-06-04.

The `ice-sh` validation confirmed OAuth, MCP tool calls, BigQuery metadata/query tools, SQL guard rejection, unauthorized project rejection, and Cloud Logging audit records.

The current pilot operating target is `ice-mp`, with `sinohara@impress.co.jp` as the only named pilot user.

Session persistence is implemented as an optional Firestore-backed control. It is not enabled in the current workflow default yet; enable it only after Firestore, runtime IAM, TTL, and restart validation are complete.

## Current Pilot Rollout: ice-mp

| Field | Value |
| --- | --- |
| Rollout name | `ice-mp` pilot |
| Target BigQuery project ID | `ice-mp` |
| Cloud Run deployment project ID | `ice-sh` |
| Cloud Run service name | `bigquery-readonly-mcp` |
| Region | `asia-northeast1` |
| Owner / requestor | 篠原邦昭 / `sinohara@impress.co.jp` |
| Initial user | `sinohara@impress.co.jp` |
| Inquiry contacts | 篠原さん / 運用担当 / 管理者 |
| Rollout pattern | Pattern B shared Cloud Run, single allowed BigQuery project for pilot |
| Status | Pilot operating |

Current deployment settings:

| Variable | Value |
| --- | --- |
| `DEFAULT_PROJECT_ID` | `ice-mp` |
| `ALLOWED_PROJECT_IDS` | `ice-mp` |
| `ALLOWED_DATASET_IDS` | empty |
| `ALLOWED_USER_EMAILS` | `sinohara@impress.co.jp` |
| `MAXIMUM_BYTES_BILLED` | `1073741824` |
| `MAX_RESULTS` | `1000` |
| `QUERY_TIMEOUT_SECONDS` | `60` |
| `SESSION_STORE_BACKEND` | `memory` |
| `FIRESTORE_SESSION_COLLECTION` | `bigquery_mcp_sessions` |

Operational notes:

- `ALLOWED_PROJECT_IDS=ice-mp` prevents accidental use of other BigQuery projects from this Cloud Run deployment.
- `ALLOWED_USER_EMAILS=sinohara@impress.co.jp` limits the pilot to the initial user.
- `ALLOWED_DATASET_IDS` is empty, so dataset access is governed by BigQuery IAM.
- GitHub Actions deploy defaults are aligned with this pilot configuration, so future deploys should not revert the service to `ice-sh` defaults.
- `SESSION_STORE_BACKEND=memory` is safe but can require re-login after Cloud Run restart, scale-out, or new revision.
- Firestore-backed session persistence can be enabled after Firestore setup and restart validation.
- Before adding users, review BigQuery IAM and decide whether `ALLOWED_USER_EMAILS` should remain named-user restricted.
- Before restricting datasets, set `ALLOWED_DATASET_IDS` and validate metadata allow/reject behavior.

## Implemented Phase 8 Controls

The following Phase 8 controls are implemented:

- `ALLOWED_PROJECT_IDS` environment variable.
- `ALLOWED_DATASET_IDS` environment variable for project-scoped dataset allowlists.
- `ALLOWED_USER_EMAILS` environment variable.
- Optional `SESSION_STORE_BACKEND=firestore` session persistence for post-login MCP sessions.
- BigQuery tool calls for projects outside `ALLOWED_PROJECT_IDS` are rejected before BigQuery API calls.
- `list_datasets` is filtered to datasets inside `ALLOWED_DATASET_IDS` when configured.
- `list_tables` and `get_table_schema` reject datasets outside `ALLOWED_DATASET_IDS` before BigQuery API calls.
- `list_projects` is filtered to allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Rejected project calls are written to audit logs with `success=false` and `rejection_reason="project_not_allowed"`.
- Rejected dataset calls are written to audit logs with `success=false` and `rejection_reason="dataset_not_allowed"`.
- Rejected user calls are written to audit logs with `success=false` and `rejection_reason="user_not_allowed"`.
- SQL guard rejections are written to audit logs with `success=false` and `rejection_reason="sql_not_allowed"`.
- BigQuery permission-denied responses are written to audit logs with `success=false` and `rejection_reason="bigquery_iam_denied"`.
- Other BigQuery or HTTP API failures are written to audit logs with `success=false` and `rejection_reason="bigquery_api_error"`.
- Other internal execution failures are written to audit logs with `success=false` and `rejection_reason="execution_error"`.
- Unit tests cover empty allowlists, allowed/rejected projects, allowed/rejected users, case-insensitive user matching, dataset filtering, dataset rejection before client creation, audit rejection categories, in-memory session behavior, encrypted token round trips, encrypted token session binding, and invalid session backend rejection.

The following Phase 8 controls have been evaluated but are not required for initial rollout:

- BigQuery audit dataset export: optional via Cloud Logging Log Router when retention/reporting/dashboard requirements exist.
- Query history UI: deferred until exported audit data and administrator review requirements are confirmed.

## Principles

- Keep BigQuery execution tied to the logged-in Google user.
- Do not use a service account to proxy BigQuery queries for all users.
- Keep SQL readonly: allow only `SELECT` and `WITH` queries.
- Manage deployment resources per GCP project.
- Prefer IAM and dataset-level permissions over broad application-side controls.
- Treat application allowlists as additional restrictions only; they must never grant access beyond BigQuery IAM.
- Keep every rollout auditable in Cloud Logging.
- Persist sessions only when the deployment project has the required Firestore controls and the security owner accepts the session TTL.
- Prefer reversible rollout controls: remove connector configuration, Cloud Run access, project/user/dataset allowlist entries, persistent session backend setting, or deployment resources.

## Initial Rollout Decisions

| Area | Phase 8 decision | Reason |
| --- | --- | --- |
| Project allowlist | Implemented with `ALLOWED_PROJECT_IDS`. Current pilot value: `ice-mp`. | Prevents accidental cross-project use while preserving runtime `project_id`. |
| Dataset allowlist | Implemented for metadata tools with `ALLOWED_DATASET_IDS`. Current pilot value: empty. | Keeps dataset access governed by BigQuery IAM unless a dataset kill switch is needed. |
| User allowlist | Implemented with optional `ALLOWED_USER_EMAILS`. Current pilot value: `sinohara@impress.co.jp`. | Limits the initial pilot to one user. |
| Domain allowlist | Required. Initial value: `impress.co.jp`. | Blocks non-company Google accounts before BigQuery access is attempted. |
| Session persistence | Optional Firestore backend implemented. Current pilot value: `memory`. | Avoids re-login after Cloud Run restart once Firestore/IAM/TTL validation is complete. |
| Per-project policy | Required. Cloud Run, Artifact Registry, Secret Manager, WIF, deploy service account, GitHub Secrets, OAuth redirect URI, health check, and optional Firestore storage must be managed per GCP project. | Keeps blast radius and deployment ownership clear. |
| BigQuery audit dataset | Evaluated. Keep Cloud Logging as the required audit source now. Add BigQuery export through a Log Router sink when retention, reporting, dashboard, or cross-project review requirements are confirmed. | Avoids storage and IAM surface before there is an operational need. |
| Query history UI | Evaluated. Do not build for initial rollout. Consider an admin-only audit browser only after audit export and review requirements are confirmed. | Cloud Logging is enough now; UI adds auth, privacy, retention, and maintenance work. |
| IAM Deny policy | Not required for normal operation. Use only for validation, break-glass restrictions, or explicit security boundaries. | Standard access should be governed by Google OAuth identity plus BigQuery IAM. |

## Rollout Patterns

### Pattern A: One Cloud Run Deployment Per Analytics Domain

Use this when each service or business domain has its own ownership, secrets, OAuth redirect URI, and operational boundary.

Default behavior:

- `DEFAULT_PROJECT_ID` is the target analytics project.
- `ALLOWED_PROJECT_IDS` contains only that project and explicitly approved adjacent projects.
- `ALLOWED_DATASET_IDS` is empty unless the rollout needs a dataset pilot boundary or kill switch.
- `ALLOWED_USER_EMAILS` is empty unless the deployment is a named-user pilot.
- `SESSION_STORE_BACKEND` starts as `memory`; use `firestore` after restart validation if session continuity is required.
- Cloud Logging remains in the deployment project.

### Pattern B: Shared Cloud Run Deployment With Multiple Allowed Projects

Use this only when the same operations team owns all target projects and accepts a shared blast radius.

Required controls:

- Set `ALLOWED_PROJECT_IDS` for every approved project.
- Optionally set `ALLOWED_DATASET_IDS` for dataset-level restrictions.
- Optionally set `ALLOWED_USER_EMAILS` for named-user pilots.
- Optionally set `SESSION_STORE_BACKEND=firestore` after Firestore readiness is confirmed.
- Document every allowed project, dataset, user boundary, session backend, and owner.
- Confirm audit filters can separate project activity.

The current `ice-mp` pilot uses the existing shared Cloud Run deployment but restricts allowed project and user values to keep the pilot narrow.

## Application-Side Allowlist Policy

Implemented environment variables:

```text
ALLOWED_PROJECT_IDS=ice-mp
ALLOWED_DATASET_IDS=
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
```

Current behavior:

- Empty `ALLOWED_PROJECT_IDS` means no application-side project restriction beyond BigQuery IAM. This is acceptable only for narrow pilots.
- Non-empty `ALLOWED_PROJECT_IDS` rejects tool calls for projects outside the list before BigQuery API calls.
- `list_projects` returns only allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Empty `ALLOWED_DATASET_IDS` means no application-side dataset restriction beyond BigQuery IAM.
- Non-empty `ALLOWED_DATASET_IDS` is a comma-separated list of `project_id:dataset_id` values.
- `list_datasets` returns only datasets in `ALLOWED_DATASET_IDS` for the requested project.
- `list_tables` and `get_table_schema` reject datasets outside `ALLOWED_DATASET_IDS` before BigQuery API calls.
- `dry_run_query` and `run_readonly_query` do not use dataset allowlist enforcement yet; they rely on SQL guard plus BigQuery IAM.
- Empty `ALLOWED_USER_EMAILS` means domain allowlist plus BigQuery IAM controls users.
- Non-empty `ALLOWED_USER_EMAILS` rejects tool calls from users outside the list before BigQuery API calls.
- Email matching for `ALLOWED_USER_EMAILS` is case-insensitive.

## Session Persistence Policy

Implemented environment variables:

```text
SESSION_STORE_BACKEND=memory
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=3600
```

Current behavior:

- `memory` stores MCP sessions in the running Cloud Run instance only.
- `firestore` stores post-login MCP sessions in Firestore so the same cookie can survive Cloud Run restart, scale-out, and new revisions until TTL expiry.
- Access tokens are encrypted before Firestore storage using AES-GCM and a key derived from `SESSION_SECRET`.
- Rotating `SESSION_SECRET` invalidates persisted sessions by design.
- Invalid persisted sessions are deleted and treated as logged out.
- OAuth authorization requests and authorization codes remain short-lived and in-memory; a login flow interrupted by a new revision may need to be retried.
- Session persistence does not change BigQuery authorization. BigQuery calls still run with the logged-in user's OAuth token and IAM.

Enable Firestore persistence only after:

1. `firestore.googleapis.com` is enabled in the Cloud Run deployment project.
2. A Firestore database exists in the deployment project.
3. The Cloud Run runtime service account has Firestore document read/write/delete permissions, typically `roles/datastore.user` unless a narrower custom role is available.
4. `SESSION_TTL_SECONDS` is approved for the pilot or rollout.
5. A restart/new-revision smoke test confirms the same `mcp_session` remains usable.

## BigQuery IAM Policy

Grant users only the permissions they need:

- `roles/bigquery.jobUser` on the project where query jobs run.
- `roles/bigquery.dataViewer` on the smallest practical dataset scope.

Avoid project-wide `dataViewer` unless the project is explicitly intended for broad analysis access.

Before declaring a project ready, check all possible access paths:

- Direct project IAM bindings for the user.
- Google Group bindings that include the user.
- Folder and organization inheritance.
- Dataset access entries such as `userByEmail`, `groupByEmail`, `domain`, and `specialGroup`.
- Authorized views or linked datasets if they are part of the analysis path.

The MCP should not compensate for excessive BigQuery IAM. If a user can query a dataset through BigQuery IAM and the project/dataset are allowed by application controls, the MCP should generally allow the readonly request and audit it.

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
9. Cloud Run environment variables are set for the target project, allowed projects, allowed datasets if any, allowed users if any, domain, limits, and session backend.
10. OAuth redirect URI and `BASE_URL` match exactly.
11. External health check uses `/health`, not `/healthz`.
12. BigQuery IAM grants are reviewed at project, dataset, table/view, folder, organization, Google Group, and domain levels.
13. If `SESSION_STORE_BACKEND=firestore` is used, Firestore API/database/runtime IAM/TTL/restart validation are complete.
14. Phase 7 validation is repeated for the target project before opening use to more users.
15. Rollback steps are documented: disable connector, remove Cloud Run invoker access, remove project/user/dataset allowlist entry, set `SESSION_STORE_BACKEND=memory`, or delete the deployment.

## Required Validation For Each Rollout

Repeat the Phase 7 validation with the target project:

1. OAuth login succeeds for an allowed-domain user.
2. `/mcp` authenticated tool call succeeds.
3. `list_projects` confirms expected allowed-project visibility.
4. `list_datasets(project_id=target)` succeeds for authorized datasets and hides denied datasets when `ALLOWED_DATASET_IDS` is set.
5. `list_tables` succeeds for a known allowed dataset.
6. `get_table_schema` succeeds for a non-sensitive validation table in an allowed dataset.
7. `dry_run_query` returns bytes processed and respects `maximumBytesBilled`.
8. `run_readonly_query` returns a bounded result set.
9. DML is rejected before BigQuery execution.
10. DDL is rejected before BigQuery execution.
11. Project outside `ALLOWED_PROJECT_IDS` is rejected before BigQuery execution.
12. User outside `ALLOWED_USER_EMAILS`, when configured, is rejected before BigQuery execution.
13. Dataset outside `ALLOWED_DATASET_IDS`, when configured, is rejected by metadata tools before BigQuery execution.
14. Unauthorized project or denied job creation returns an error, not a successful MCP response.
15. Cloud Logging records successful reads and failed/rejected attempts with `success`, `error`, `rejection_reason`, `user_email`, `tool`, and `project_id`.
16. If Firestore sessions are enabled, a logged-in MCP session survives a Cloud Run restart or new revision until `SESSION_TTL_SECONDS` expires.

Use a small validation table and avoid company-sensitive data in validation output.

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
- `rejection_reason` for failed or rejected calls

Recommended Cloud Logging filters:

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.project_id="ice-mp"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.success=false
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.rejection_reason="project_not_allowed"
```

## BigQuery Audit Dataset Export Evaluation

Status: evaluated in Phase 8 P2. Do not implement as a required control for the initial rollout. Keep Cloud Logging as the required audit source, and add BigQuery export only when durable retention, reporting, or dashboard requirements justify the extra operational surface.

Recommendation: use a Cloud Logging Log Router sink to export MCP audit logs to BigQuery. Do not write audit rows directly from the MCP application by default.

## Query History UI Evaluation

Status: evaluated in Phase 8 P2. Do not build a query history UI for the initial rollout. Cloud Logging is enough for immediate investigation, and BigQuery audit export is the better next foundation if recurring review is needed.

## Phase 8 Implementation Backlog

| Priority | Status | Item | Purpose |
| --- | --- | --- | --- |
| P0 | Complete | Implement `ALLOWED_PROJECT_IDS` enforcement. | Prevent cross-project use from a shared deployment. |
| P0 | Complete | Add tests for allowed and rejected project IDs. | Prove allowlist behavior before broad rollout. |
| P1 | Complete | Implement optional `ALLOWED_USER_EMAILS`. | Support limited pilots and sensitive deployments. |
| P1 | Complete | Add audit fields for rejection reason category. | Project, user, SQL guard, BigQuery IAM denied, BigQuery API error, and execution-error failures are categorized. |
| P1 | Complete | Document per-project rollout template. | Make future rollouts repeatable. |
| P2 | Complete | Evaluate BigQuery audit dataset export. | Cloud Logging remains required; Log Router to BigQuery is the recommended optional path when retention/reporting requirements exist. |
| P2 | Complete | Consider query history UI. | Not required now; defer until audit export and administrator review requirements are confirmed. |
| P2 | Complete | Implement project-scoped dataset allowlist for metadata tools. | Optional defense-in-depth for dataset visibility and metadata access. |
| P2 | Implemented, activation pending | Implement optional Firestore-backed session persistence. | Reduce re-login caused by Cloud Run restarts, scale-out, and new revisions. |
| P2 | Pending | Enable and validate Firestore session persistence in Cloud Run. | Requires Firestore API/database, runtime IAM, TTL decision, deploy, and restart smoke test. |
| Pilot | In progress | Operate `ice-mp` pilot for `sinohara@impress.co.jp`. | Start practical use with a narrow project/user boundary. |

## Follow-Up Hardening Candidates

These are not required to operate the `ice-mp` pilot, but should be considered before broader use:

- Decide whether additional users should remain in `ALLOWED_USER_EMAILS` or whether domain+IAM is enough.
- Reliable query SQL reference extraction if dataset allowlist enforcement is ever needed for `dry_run_query` and `run_readonly_query`.
- Enable Firestore-backed persistent sessions after Firestore/IAM/TTL/restart validation is complete.
- Implement BigQuery audit dataset export after retention and reporting requirements are confirmed.
- Query history UI for administrators after audit export and review requirements are confirmed.
- Dedicated runtime service account instead of the default compute service account.

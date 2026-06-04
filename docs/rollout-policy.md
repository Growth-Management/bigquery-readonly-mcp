# Rollout Policy

This document captures the Phase 8 rollout policy for expanding `bigquery-readonly-mcp` beyond the initial `ice-sh` validation.

## Phase 8 Status

Phase 8 is ready for controlled rollout after Phase 7 completed on 2026-06-04.

The `ice-sh` validation confirmed:

- OAuth login with an `impress.co.jp` user.
- Authenticated MCP tool calls to `/mcp`.
- BigQuery tools for project, dataset, table, schema, dry run, and readonly query execution.
- SQL guard rejection for DML and DDL.
- Unauthorized project rejection through user-effective IAM, verified with HTTP `403 Forbidden`.
- Cloud Logging audit records for successful and rejected tool calls.

Phase 8 focuses on controlled multi-project rollout, not on changing the core identity model.

## Implemented Phase 8 Controls

The following Phase 8 controls are implemented:

- `ALLOWED_PROJECT_IDS` environment variable.
- `ALLOWED_DATASET_IDS` environment variable for project-scoped dataset allowlists.
- `ALLOWED_USER_EMAILS` environment variable.
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
- Unit tests cover empty allowlists, allowed/rejected projects, allowed/rejected users, case-insensitive user matching, dataset filtering, dataset rejection before client creation, and audit rejection categories.
- The initial Cloud Run deployment sets `ALLOWED_PROJECT_IDS=ice-sh`, `ALLOWED_DATASET_IDS=` and `ALLOWED_USER_EMAILS=`. Empty dataset/user allowlists preserve the current `ice-sh` behavior.

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
- Prefer reversible rollout controls: remove connector configuration, Cloud Run access, project/user/dataset allowlist entries, or deployment resources.

## Initial Rollout Decisions

| Area | Phase 8 decision | Reason |
| --- | --- | --- |
| Project allowlist | Implemented with `ALLOWED_PROJECT_IDS`. Each Cloud Run deployment should set the intended project list. | Prevents accidental cross-project use while preserving runtime `project_id`. |
| Dataset allowlist | Implemented for metadata tools with `ALLOWED_DATASET_IDS`. Leave empty by default; enable only when operational policy needs a stricter or easier-to-disable boundary than IAM alone. | Adds a dataset kill switch and pilot boundary without replacing BigQuery IAM. |
| User allowlist | Implemented with optional `ALLOWED_USER_EMAILS`. Keep it empty for normal domain+IAM operation; set it for sensitive deployments or limited pilots. | Supports named-user restriction when needed. |
| Domain allowlist | Required. Initial value: `impress.co.jp`. | Blocks non-company Google accounts before BigQuery access is attempted. |
| Per-project policy | Required. Cloud Run, Artifact Registry, Secret Manager, WIF, deploy service account, GitHub Secrets, OAuth redirect URI, and health check must be managed per GCP project. | Keeps blast radius and deployment ownership clear. |
| BigQuery audit dataset | Evaluated. Keep Cloud Logging as the required audit source now. Add BigQuery export through a Log Router sink when retention, reporting, dashboard, or cross-project review requirements are confirmed. | Avoids storage and IAM surface before there is an operational need. |
| Query history UI | Evaluated. Do not build for initial rollout. Consider an admin-only audit browser only after audit export and review requirements are confirmed. | Cloud Logging is enough now; UI adds auth, privacy, retention, and maintenance work. |
| IAM Deny policy | Not required for normal operation. Use only for validation, break-glass restrictions, or explicit security boundaries. | Standard access should be governed by Google OAuth identity plus BigQuery IAM. |

## Rollout Patterns

### Pattern A: One Cloud Run Deployment Per Analytics Domain

Use this when each service or business domain has its own ownership, secrets, OAuth redirect URI, and operational boundary.

Recommended for:

- Projects with different administrators.
- Projects with different allowed users.
- Projects requiring different limits or audit retention.
- Sensitive datasets where isolated Cloud Run and Secret Manager configuration is valuable.

Default behavior:

- `DEFAULT_PROJECT_ID` is the target analytics project.
- `ALLOWED_PROJECT_IDS` contains only that project and explicitly approved adjacent projects.
- `ALLOWED_DATASET_IDS` is empty unless the rollout needs a dataset pilot boundary or kill switch.
- `ALLOWED_USER_EMAILS` is empty unless the deployment is a named-user pilot.
- Cloud Logging remains in the deployment project.

### Pattern B: Shared Cloud Run Deployment With Multiple Allowed Projects

Use this only when the same operations team owns all target projects and accepts a shared blast radius.

Required controls:

- Set `ALLOWED_PROJECT_IDS` for every approved project.
- Optionally set `ALLOWED_DATASET_IDS` for dataset-level restrictions.
- Optionally set `ALLOWED_USER_EMAILS` for named-user pilots.
- Document every allowed project, dataset, and owner.
- Confirm audit filters can separate project activity.

Recommended initial expansion: use Pattern A for the first non-`ice-sh` rollout.

## Application-Side Allowlist Policy

Implemented environment variables:

```text
ALLOWED_PROJECT_IDS=ice-sh,another-project
ALLOWED_DATASET_IDS=ice-sh:ice_sh_datamart,ice-sh:ice_sh_source
ALLOWED_USER_EMAILS=sinohara@impress.co.jp,another-user@impress.co.jp
```

Current behavior:

- Empty `ALLOWED_PROJECT_IDS` means no application-side project restriction beyond BigQuery IAM. This is acceptable only for narrow pilots.
- Non-empty `ALLOWED_PROJECT_IDS` rejects tool calls for projects outside the list before BigQuery API calls.
- `list_projects` returns only allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Empty `ALLOWED_DATASET_IDS` means no application-side dataset restriction beyond BigQuery IAM.
- Non-empty `ALLOWED_DATASET_IDS` is a comma-separated list of `project_id:dataset_id` values.
- `list_datasets` returns only datasets in `ALLOWED_DATASET_IDS` for the requested project.
- `list_tables` and `get_table_schema` reject datasets outside `ALLOWED_DATASET_IDS` before BigQuery API calls.
- `dry_run_query` and `run_readonly_query` do not use dataset allowlist enforcement yet; they rely on SQL guard plus BigQuery IAM. Avoid ad hoc SQL string parsing for dataset references.
- Empty `ALLOWED_USER_EMAILS` means domain allowlist plus BigQuery IAM controls users.
- Non-empty `ALLOWED_USER_EMAILS` rejects tool calls from users outside the list before BigQuery API calls.
- Email matching for `ALLOWED_USER_EMAILS` is case-insensitive.

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
9. Cloud Run environment variables are set for the target project, allowed projects, allowed datasets if any, allowed users if any, domain, and limits.
10. OAuth redirect URI and `BASE_URL` match exactly.
11. External health check uses `/health`, not `/healthz`.
12. BigQuery IAM grants are reviewed at project, dataset, table/view, folder, organization, Google Group, and domain levels.
13. Phase 7 validation is repeated for the target project before opening use to more users.
14. Rollback steps are documented: disable connector, remove Cloud Run invoker access, remove project/user/dataset allowlist entry, or delete the deployment.

## Rollout Record Template

Copy this section for each new project rollout.

### Summary

| Field | Value |
| --- | --- |
| Rollout name |  |
| Target BigQuery project ID |  |
| Cloud Run deployment project ID |  |
| Cloud Run service name | `bigquery-readonly-mcp` |
| Region | `asia-northeast1` |
| Owner / requestor |  |
| Operations owner |  |
| Security reviewer |  |
| Rollout pattern | Pattern A dedicated / Pattern B shared |
| Intended users |  |
| Intended datasets |  |
| Status | Draft / Validating / Validated / Paused / Retired |

### Environment

| Variable | Expected | Actual | Status |
| --- | --- | --- | --- |
| `BASE_URL` | Cloud Run URL or custom domain |  |  |
| `ALLOWED_DOMAIN` | `impress.co.jp` |  |  |
| `DEFAULT_PROJECT_ID` | Target project ID |  |  |
| `ALLOWED_PROJECT_IDS` | Target project plus approved adjacent projects |  |  |
| `ALLOWED_DATASET_IDS` | Empty or approved `project_id:dataset_id` entries |  |  |
| `ALLOWED_USER_EMAILS` | Empty unless named-user pilot |  |  |
| `MAXIMUM_BYTES_BILLED` | `1073741824` unless approved otherwise |  |  |
| `MAX_RESULTS` | `1000` unless approved otherwise |  |  |
| `QUERY_TIMEOUT_SECONDS` | `60` unless approved otherwise |  |  |

### Validation Checklist

| Check | Expected result | Actual result | Status |
| --- | --- | --- | --- |
| `/health` | HTTP 200 and `{"status":"ok"}` |  |  |
| OAuth login | Allowed-domain login succeeds |  |  |
| `/mcp` authenticated call | JSON-RPC tool call succeeds |  |  |
| `list_projects` | Expected allowed project visibility |  |  |
| `list_datasets` | Target datasets returned; denied datasets hidden if allowlist set |  |  |
| `list_tables` | Validation table visible for allowed dataset |  |  |
| `get_table_schema` | Schema returned for allowed dataset |  |  |
| `dry_run_query` | Bytes processed returned, under limit |  |  |
| `run_readonly_query` | Bounded rows returned |  |  |
| DML rejection | Rejected before BigQuery execution |  |  |
| DDL rejection | Rejected before BigQuery execution |  |  |
| Project outside `ALLOWED_PROJECT_IDS` | Rejected before BigQuery execution |  |  |
| User outside `ALLOWED_USER_EMAILS`, if configured | Rejected before BigQuery execution |  |  |
| Dataset outside `ALLOWED_DATASET_IDS`, if configured | Metadata tools reject before BigQuery execution |  |  |
| Unauthorized project / denied job creation | Error, not successful MCP response |  |  |
| Audit log success case | `success=true` record present |  |  |
| Audit log rejection case | `success=false` record present with expected `rejection_reason` |  |  |

### Rollback Plan

| Rollback action | Owner | Procedure | Status |
| --- | --- | --- | --- |
| Disable MCP connector |  |  |  |
| Remove project from `ALLOWED_PROJECT_IDS` |  |  |  |
| Remove dataset from `ALLOWED_DATASET_IDS` |  |  |  |
| Remove user from `ALLOWED_USER_EMAILS` |  |  |  |
| Remove Cloud Run invoker access if restricted |  |  |  |
| Revert GitHub deployment |  |  |  |
| Delete Cloud Run service if needed |  |  |  |

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

`rejection_reason` values:

| Value | Meaning |
| --- | --- |
| `project_not_allowed` | `project_id` is outside `ALLOWED_PROJECT_IDS`. |
| `dataset_not_allowed` | `project_id:dataset_id` is outside `ALLOWED_DATASET_IDS` for dataset-targeting metadata tools. |
| `user_not_allowed` | user email is outside `ALLOWED_USER_EMAILS`. |
| `sql_not_allowed` | SQL guard rejected a non-readonly or unsafe query. |
| `bigquery_iam_denied` | BigQuery returned permission denied, including HTTP 403. |
| `bigquery_api_error` | BigQuery or HTTP API failed for a non-403 API reason. |
| `execution_error` | Internal execution failed outside the known categories. |

Recommended Cloud Logging filters:

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.project_id="<project_id>"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.success=false
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.rejection_reason="dataset_not_allowed"
```

## BigQuery Audit Dataset Export Evaluation

Status: evaluated in Phase 8 P2. Do not implement as a required control for the initial rollout. Keep Cloud Logging as the required audit source, and add BigQuery export only when durable retention, reporting, or dashboard requirements justify the extra operational surface.

Recommendation: use a Cloud Logging Log Router sink to export MCP audit logs to BigQuery. Do not write audit rows directly from the MCP application by default.

Recommended Log Router filter:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
```

Enable BigQuery export when retention, recurring reports, dashboards, cross-project review, or incident-analysis requirements justify it. Estimated effort: about 1.0-2.5 hours depending on IAM approval speed and whether the audit dataset already exists.

## Query History UI Evaluation

Status: evaluated in Phase 8 P2. Do not build a query history UI for the initial rollout. Cloud Logging is enough for immediate investigation, and BigQuery audit export is the better next foundation if recurring review is needed.

If implemented later, the first version should be an admin-only audit browser with date range, user, project, tool, success/failure, rejection reason, dataset, table, and event-detail filters. It should not show query result rows. Estimated effort after audit export and access policy are defined: about 1.5-4.0 days.

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

## Follow-Up Hardening Candidates

These are not required to complete the initial `ice-sh` rollout, but should be considered before broad multi-project use:

- Reliable query SQL reference extraction if dataset allowlist enforcement is ever needed for `dry_run_query` and `run_readonly_query`.
- Implement BigQuery audit dataset export after retention and reporting requirements are confirmed.
- Query history UI for administrators after audit export and review requirements are confirmed.
- Dedicated runtime service account instead of the default compute service account.
- Persistent OAuth/session storage if Cloud Run restarts or session longevity become operational issues.

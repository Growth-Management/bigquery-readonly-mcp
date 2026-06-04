# Rollout Policy

This document captures the Phase 8 rollout policy for expanding `bigquery-readonly-mcp` beyond the initial `ice-sh` validation.

## Phase 8 Status

Phase 8 is ready for rollout planning after Phase 7 completed on 2026-06-04.

The `ice-sh` validation confirmed:

- OAuth login with an `impress.co.jp` user.
- Authenticated MCP tool calls to `/mcp`.
- BigQuery tools for project, dataset, table, schema, dry run, and readonly query execution.
- SQL guard rejection for DML and DDL.
- Unauthorized project rejection through user-effective IAM, verified with HTTP `403 Forbidden`.
- Cloud Logging audit records for successful and rejected tool calls.

Phase 8 should now focus on controlled multi-project rollout, not on changing the core identity model.

## Implemented Phase 8 Controls

The following Phase 8 controls are implemented or evaluated:

- `ALLOWED_PROJECT_IDS` environment variable.
- `ALLOWED_USER_EMAILS` environment variable.
- BigQuery tool calls for projects outside `ALLOWED_PROJECT_IDS` are rejected before BigQuery API calls.
- BigQuery tool calls from users outside `ALLOWED_USER_EMAILS` are rejected before BigQuery API calls.
- Rejected project calls are written to audit logs with `success=false` and `rejection_reason="project_not_allowed"`.
- Rejected user calls are written to audit logs with `success=false` and `rejection_reason="user_not_allowed"`.
- SQL guard rejections are written to audit logs with `success=false` and `rejection_reason="sql_not_allowed"`.
- BigQuery permission-denied responses are written to audit logs with `success=false` and `rejection_reason="bigquery_iam_denied"`.
- Other BigQuery or HTTP API failures are written to audit logs with `success=false` and `rejection_reason="bigquery_api_error"`.
- Other internal execution failures are written to audit logs with `success=false` and `rejection_reason="execution_error"`.
- `list_projects` is filtered to allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Unit tests cover empty allowlists, allowed project, rejected project, default-project rejection, allowed user, rejected user, case-insensitive email matching, SQL guard rejection category, BigQuery IAM-denied category, BigQuery API-error category, and generic execution-error category.
- BigQuery audit dataset export has been evaluated. Cloud Logging remains the required audit sink; BigQuery export is recommended only when retention, reporting, or dashboard requirements need it.
- Query history UI has been evaluated. It is not required for initial rollout; build it only after exported audit data and administrator review requirements are confirmed.
- Project-scoped dataset allowlist has been evaluated. BigQuery IAM remains the primary dataset boundary; application-side dataset allowlist is optional and should be added only for stricter operational policy.
- The initial Cloud Run deployment sets `ALLOWED_PROJECT_IDS=ice-sh` and leaves `ALLOWED_USER_EMAILS` empty.

## Principles

- Keep BigQuery execution tied to the logged-in Google user.
- Do not use a service account to proxy BigQuery queries for all users.
- Keep SQL readonly: allow only `SELECT` and `WITH` queries.
- Manage deployment resources per GCP project.
- Prefer IAM and dataset-level permissions over broad application-side bypasses.
- Keep every rollout auditable in Cloud Logging.
- Treat `project_id` as a required operational decision, even though the MCP tool schema allows it at runtime.
- Prefer a reversible rollout: every new project should be easy to disable by removing connector configuration, Cloud Run access, or project allowlist entries.

## Initial Rollout Decisions

| Area | Phase 8 decision | Reason |
| --- | --- | --- |
| Project allowlist | Implemented with `ALLOWED_PROJECT_IDS`. Each Cloud Run deployment should set the intended project list. | Prevents accidental cross-project use while preserving the generic `project_id` tool design. |
| Dataset allowlist | Evaluated. Use BigQuery IAM first. Grant `roles/bigquery.dataViewer` at dataset scope wherever possible. Add project-scoped `ALLOWED_DATASET_IDS` only when operational policy requires a stricter boundary than IAM. | Dataset-level IAM is the source of truth; app-side dataset allowlist is useful as a defense-in-depth control but adds policy duplication and maintenance. |
| User allowlist | Implemented with optional `ALLOWED_USER_EMAILS`. Keep it empty for normal domain+IAM operation; set it for sensitive deployments or limited pilots. | Keeps onboarding simple by default while supporting named-user restriction when needed. |
| Domain allowlist | Required. Initial value: `impress.co.jp`. | Blocks non-company Google accounts before BigQuery access is attempted. |
| Per-project policy | Required. Cloud Run, Artifact Registry, Secret Manager, WIF, deploy service account, GitHub Secrets, OAuth redirect URI, and health check must be managed per GCP project. | Keeps blast radius and deployment ownership clear. |
| BigQuery audit dataset | Evaluated. Keep Cloud Logging as the required audit source now. Add BigQuery export through a Log Router sink when retention, reporting, dashboard, or cross-project review requirements are confirmed. | Avoids adding storage and IAM surface before there is an operational need, while leaving a clear path for durable audit analytics. |
| Query history UI | Evaluated. Do not build for initial rollout. Consider a thin admin-only UI only after audit export/query history requirements are confirmed. | Cloud Logging is enough now; a UI adds authentication, authorization, filtering, and privacy-review work. |
| IAM Deny policy | Not required for normal operation. Use only for validation, break-glass restrictions, or explicit security boundaries. | Standard access should be governed by Google OAuth identity plus BigQuery IAM. Deny policies are powerful and should stay exceptional. |

## Rollout Patterns

Choose one rollout pattern before adding a new project.

### Pattern A: One Cloud Run Deployment Per Analytics Domain

Use this when each service or business domain has its own ownership, secrets, OAuth redirect URI, and operational boundary.

Recommended for:

- Projects with different administrators.
- Projects with different allowed users.
- Projects requiring different maximum bytes billed or audit retention.
- Sensitive datasets where isolated Cloud Run and Secret Manager configuration is valuable.

Default behavior:

- `DEFAULT_PROJECT_ID` is the target analytics project.
- `ALLOWED_PROJECT_IDS` contains only that project and explicitly approved adjacent projects.
- `ALLOWED_USER_EMAILS` is empty unless the deployment is a named-user pilot.
- Cloud Logging remains in the deployment project.

### Pattern B: Shared Cloud Run Deployment With Multiple Allowed Projects

Use this only when the same operations team owns all target projects and accepts a shared blast radius.

Required controls:

- Set `ALLOWED_PROJECT_IDS` for every approved project.
- Optionally set `ALLOWED_USER_EMAILS` for named-user pilots.
- Document every allowed project and owner.
- Confirm audit filters can separate project activity.

### Recommended Initial Expansion

Use Pattern A for the first non-`ice-sh` rollout. It is operationally simpler to explain and safer if a project needs to be disabled or reconfigured.

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
9. Cloud Run environment variables are set for the target project, allowed projects, allowed users if any, domain, and limits.
10. OAuth redirect URI and `BASE_URL` match exactly.
11. External health check uses `/health`, not `/healthz`.
12. BigQuery IAM grants are reviewed at project, dataset, table/view, folder, organization, Google Group, and domain levels.
13. Phase 7 validation is repeated for the target project before opening use to more users.
14. Rollback steps are documented: disable connector, remove Cloud Run invoker access, remove project/user allowlist entry, or delete the deployment.

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
| `ALLOWED_USER_EMAILS` | Empty unless named-user pilot |  |  |
| `MAXIMUM_BYTES_BILLED` | `1073741824` unless approved otherwise |  |  |
| `MAX_RESULTS` | `1000` unless approved otherwise |  |  |
| `QUERY_TIMEOUT_SECONDS` | `60` unless approved otherwise |  |  |

### BigQuery IAM Review

| Access path | Reviewed? | Notes |
| --- | --- | --- |
| Direct project IAM for target users |  |  |
| Google Group project IAM |  |  |
| Folder / organization inheritance |  |  |
| Dataset `userByEmail` entries |  |  |
| Dataset `groupByEmail` entries |  |  |
| Dataset `domain` entries |  |  |
| Dataset `specialGroup` / `projectReaders` entries |  |  |
| Authorized views / linked datasets |  |  |
| Broad project `dataViewer`, `viewer`, `editor`, or `owner` |  |  |

### Validation Target

| Field | Value |
| --- | --- |
| Validation dataset |  |
| Validation table |  |
| Validation SQL |  |
| Rejected project test |  |
| Rejected user test, if configured |  |

### Validation Checklist

| Check | Expected result | Actual result | Status |
| --- | --- | --- | --- |
| `/health` | HTTP 200 and `{"status":"ok"}` |  |  |
| OAuth login | Allowed-domain login succeeds |  |  |
| `/mcp` authenticated call | JSON-RPC tool call succeeds |  |  |
| `list_projects` | Expected allowed project visibility |  |  |
| `list_datasets` | Target datasets returned |  |  |
| `list_tables` | Validation table visible |  |  |
| `get_table_schema` | Schema returned |  |  |
| `dry_run_query` | Bytes processed returned, under limit |  |  |
| `run_readonly_query` | Bounded rows returned |  |  |
| DML rejection | Rejected before BigQuery execution |  |  |
| DDL rejection | Rejected before BigQuery execution |  |  |
| Project outside `ALLOWED_PROJECT_IDS` | Rejected before BigQuery execution |  |  |
| User outside `ALLOWED_USER_EMAILS`, if configured | Rejected before BigQuery execution |  |  |
| Dataset outside project-scoped allowlist, if configured | Rejected before BigQuery execution |  |  |
| Unauthorized project / denied job creation | Error, not successful MCP response |  |  |
| Audit log success case | `success=true` record present |  |  |
| Audit log rejection case | `success=false` record present with expected `rejection_reason` |  |  |

### Rollback Plan

| Rollback action | Owner | Procedure | Status |
| --- | --- | --- | --- |
| Disable MCP connector |  |  |  |
| Remove project from `ALLOWED_PROJECT_IDS` |  |  |  |
| Remove user from `ALLOWED_USER_EMAILS` |  |  |  |
| Remove dataset from project-scoped dataset allowlist, if configured |  |  |  |
| Remove Cloud Run invoker access if restricted |  |  |  |
| Revert GitHub deployment |  |  |  |
| Delete Cloud Run service if needed |  |  |  |

### Sign-Off

| Role | Name | Date | Notes |
| --- | --- | --- | --- |
| Requestor |  |  |  |
| Operations owner |  |  |  |
| Security reviewer |  |  |  |
| BigQuery data owner |  |  |  |

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

The MCP should not compensate for excessive BigQuery IAM. If a user can query a dataset through BigQuery IAM and the project is allowed by `ALLOWED_PROJECT_IDS`, the MCP should generally allow the readonly request and audit it. Use `ALLOWED_USER_EMAILS` only when the deployment itself must be restricted to named users.

## Application-Side Allowlist Policy

The generic MCP design keeps `project_id` runtime-selectable. Broad rollout uses explicit allowlist controls to avoid accidental cross-project access.

Implemented environment variables:

```text
ALLOWED_PROJECT_IDS=ice-sh,another-project
ALLOWED_USER_EMAILS=sinohara@impress.co.jp,another-user@impress.co.jp
```

Evaluated but not implemented by default:

```text
ALLOWED_DATASET_IDS=ice-sh:ice_sh_datamart,ice-sh:ice_sh_source
```

Current behavior:

- Empty `ALLOWED_PROJECT_IDS` means no application-side project restriction beyond BigQuery IAM. This is acceptable only for narrow pilots.
- Non-empty `ALLOWED_PROJECT_IDS` rejects tool calls for projects outside the list before BigQuery API calls.
- `list_projects` returns only allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Empty `ALLOWED_USER_EMAILS` means domain allowlist plus BigQuery IAM controls users.
- Non-empty `ALLOWED_USER_EMAILS` rejects tool calls from users outside the list before BigQuery API calls.
- Email matching for `ALLOWED_USER_EMAILS` is case-insensitive.
- Dataset allowlist remains optional. If implemented, it must be project-scoped and should never grant access beyond BigQuery IAM.

## Required Validation For Each Rollout

Repeat the Phase 7 validation with the target project:

1. OAuth login succeeds for an allowed-domain user.
2. `/mcp` authenticated tool call succeeds.
3. `list_projects` confirms expected allowed-project visibility.
4. `list_datasets(project_id=target)` succeeds for an authorized dataset.
5. `list_tables` succeeds for a known dataset.
6. `get_table_schema` succeeds for a non-sensitive validation table.
7. `dry_run_query` returns bytes processed and respects `maximumBytesBilled`.
8. `run_readonly_query` returns a bounded result set.
9. DML is rejected before BigQuery execution.
10. DDL is rejected before BigQuery execution.
11. Project outside `ALLOWED_PROJECT_IDS` is rejected before BigQuery execution.
12. User outside `ALLOWED_USER_EMAILS`, when configured, is rejected before BigQuery execution.
13. Dataset outside project-scoped dataset allowlist, when configured, is rejected before BigQuery execution.
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
jsonPayload.rejection_reason="project_not_allowed"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.rejection_reason="user_not_allowed"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.rejection_reason="sql_not_allowed"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.rejection_reason="bigquery_iam_denied"
```

## BigQuery Audit Dataset Export Evaluation

Status: evaluated in Phase 8 P2. Do not implement as a required control for the initial rollout. Keep Cloud Logging as the required audit source, and add BigQuery export only when durable retention, reporting, or dashboard requirements justify the extra operational surface.

### Recommendation

Use a Cloud Logging Log Router sink to export MCP audit logs to BigQuery. Do not write audit rows directly from the MCP application as the default approach.

This preserves the current single audit path:

1. MCP writes one structured JSON audit event to stdout.
2. Cloud Run sends stdout to Cloud Logging.
3. Cloud Logging remains the source of truth for immediate investigation.
4. Optional Log Router sink exports matching audit events to a BigQuery dataset for retention and analytics.

### When To Enable

Enable BigQuery export when at least one of these is true:

- Audit retention must exceed the Cloud Logging retention policy.
- Security or operations needs recurring reports by user, project, tool, or rejection reason.
- Multiple Cloud Run deployments need a shared audit review surface.
- Query history UI or dashboard work begins.
- Incident review requires joining MCP audit logs with other BigQuery or access-control data.

Do not enable it only because the MCP can produce logs. Cloud Logging already satisfies the Phase 7 and initial Phase 8 audit requirement.

### Preferred Architecture

Recommended destination:

- Dataset name: `bigquery_mcp_audit`
- Table source: Cloud Logging BigQuery sink tables generated from the `bigquery_mcp_tool_call` filter
- Dataset location: same region policy as the deployment project, preferably `asia-northeast1` when supported by the surrounding analytics policy
- Retention: define explicitly before enabling, for example 180 days, 400 days, or the organization security standard

Recommended Log Router filter:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
```

For a shared audit dataset across multiple deployments, keep these fields queryable:

- Cloud project that emitted the log
- Cloud Run service name
- `user_email`
- `tool`
- `project_id`
- `dataset`
- `table`
- `bytes_processed`
- `success`
- `error`
- `rejection_reason`
- log timestamp

### Why Not Direct Application Writes

Directly inserting audit rows from the MCP application into BigQuery is not the preferred default because it would:

- Add a second BigQuery write path to a read-only MCP service.
- Require extra runtime service account permissions.
- Make audit success depend on an additional application-side API call.
- Increase the chance that an audit write failure affects user-facing MCP behavior.

If direct writes are ever required, they should be implemented as a separate, explicitly reviewed hardening task with failure isolation, no user token use, and clear runtime service account permissions.

### IAM And Safety Requirements

When enabling Log Router export:

- Grant the Log Router sink writer identity only the BigQuery permissions needed to write to the audit dataset.
- Do not grant MCP runtime code permission to write audit rows unless direct writes are separately approved.
- Restrict dataset read access to security, operations, and approved administrators.
- Avoid storing raw query result data. The current audit payload contains metadata, not result rows.
- Treat `error` as potentially sensitive operational text and restrict read access accordingly.

### Validation Plan

Before declaring BigQuery export ready:

1. Create or identify the audit dataset.
2. Create a Log Router sink with the recommended filter.
3. Run one successful MCP tool call.
4. Run one rejected project or SQL guard call.
5. Confirm exported rows contain `success=true` and `success=false` records.
6. Confirm `rejection_reason` is populated for rejected calls.
7. Confirm dashboard/report queries can filter by `user_email`, `project_id`, `tool`, and `rejection_reason`.
8. Confirm dataset IAM is limited to approved reviewers.
9. Confirm retention and deletion policy are documented.

### Estimated Effort

| Task | Estimated time |
| --- | --- |
| Confirm retention and reader policy | 15-30 minutes |
| Create dataset and Log Router sink | 15-30 minutes |
| IAM review and access grant | 15-30 minutes |
| Run validation calls and query exported rows | 20-40 minutes |
| Document final rollout record | 10-20 minutes |

Total estimate: about 1.0-2.5 hours, depending on IAM approval speed and whether the audit dataset already exists.

## Query History UI Evaluation

Status: evaluated in Phase 8 P2. Do not build a query history UI for the initial rollout. Cloud Logging is enough for immediate investigation, and BigQuery audit export is the better next foundation if recurring review is needed.

### Recommendation

Defer UI implementation until all of these are true:

- Administrators have a recurring review workflow that Cloud Logging filters do not satisfy.
- Audit events are exported to BigQuery or another durable queryable store.
- The intended viewers and retention policy are approved.
- The UI scope is limited to audit metadata, not query result data.

The first version should be an admin-only audit browser, not a user-facing analytics product.

### Minimum Useful UI

If implemented, the first version should support:

- Date range filter.
- User email filter.
- BigQuery project filter.
- Tool filter.
- Success / failure filter.
- `rejection_reason` filter.
- Dataset and table filters when present.
- Detail view for a single audit event.

Avoid showing query result rows. If SQL text is added later, treat it as sensitive and review retention and masking rules first.

### Why It Is Not Needed Now

A UI would add:

- Authentication and authorization work for administrators.
- A new frontend or internal app surface to maintain.
- Privacy review for user activity data.
- Retention and access-control decisions that are not yet required.

Cloud Logging and optional BigQuery export cover the current audit need with less operational surface.

### Adoption Trigger

Revisit UI implementation when at least one of these appears:

- Multiple deployments need daily or weekly audit review.
- Security needs a dashboard by user, project, tool, and rejection category.
- BigQuery audit export is enabled and administrators cannot use SQL/Looker Studio comfortably.
- Incident response repeatedly needs the same manual log investigation steps.

### Estimated Effort

| Task | Estimated time |
| --- | --- |
| Confirm viewers, retention, and privacy requirements | 30-60 minutes |
| Define audit source and query contract | 30-60 minutes |
| Build minimal admin-only UI | 0.5-1.5 days |
| Add access control and deployment path | 0.5-1.0 day |
| Validate filters and audit visibility | 0.5 day |

Total estimate: about 1.5-4.0 days after audit export and access policy are defined.

## Project-Scoped Dataset Allowlist Evaluation

Status: evaluated in Phase 8 P2. Do not implement as a required control for the initial rollout. BigQuery IAM remains the primary dataset boundary. Add an application-side dataset allowlist only when operational policy needs a stricter or easier-to-disable boundary than IAM alone.

### Recommendation

If implemented, use a project-scoped allowlist such as:

```text
ALLOWED_DATASET_IDS=ice-sh:ice_sh_datamart,ice-sh:ice_sh_source
```

The allowlist must only restrict access. It must never grant access beyond the logged-in user's BigQuery IAM.

### When To Enable

Enable a project-scoped dataset allowlist when at least one of these is true:

- Target users have broad project-level BigQuery permissions that cannot be narrowed quickly.
- A rollout should expose only a small set of approved datasets during a pilot.
- The data owner wants an application-level kill switch for a dataset.
- Multiple datasets exist in the same project but only some are approved for ChatGPT access.
- Dataset IAM is inherited or group-based in a way that is hard to review during rollout.

Do not enable it as a replacement for IAM cleanup. The preferred long-term boundary is still dataset-level BigQuery IAM.

### Scope And Behavior

If built, apply dataset allowlist checks before BigQuery API calls for tools that target or reveal datasets:

- `list_datasets`: return only allowed datasets for the requested project.
- `list_tables`: reject if `project_id:dataset_id` is not allowed.
- `get_table_schema`: reject if `project_id:dataset_id` is not allowed.
- `dry_run_query`: hard to enforce safely without SQL parsing for referenced datasets; keep this out of scope unless reliable table-reference extraction is added.
- `run_readonly_query`: hard to enforce safely without SQL parsing for referenced datasets; keep this out of scope unless reliable table-reference extraction is added.

For query tools, avoid ad hoc string parsing. Use BigQuery IAM and SQL guard until a reliable parser or BigQuery job metadata strategy is approved.

### Audit Requirements

If implemented, dataset allowlist rejections should use:

```text
rejection_reason="dataset_not_allowed"
```

Audit logs should include `project_id`, `dataset`, `tool`, `user_email`, `success=false`, and the rejection reason.

### Risks

- Duplicates policy already represented in BigQuery IAM.
- Can become stale when datasets are renamed or new datasets are added.
- Query SQL may reference multiple datasets, views, or authorized views that are not obvious from a simple tool argument.
- Overly strict allowlists can block legitimate reads even when IAM allows them.

### Validation Plan

Before declaring dataset allowlist ready:

1. Configure one allowed dataset and one denied dataset in the same project.
2. Confirm `list_datasets` hides the denied dataset.
3. Confirm `list_tables` and `get_table_schema` succeed for the allowed dataset.
4. Confirm `list_tables` and `get_table_schema` reject the denied dataset before BigQuery API calls.
5. Confirm the rejection audit log includes `rejection_reason="dataset_not_allowed"`.
6. Confirm query tools still rely on SQL guard plus BigQuery IAM unless reliable reference extraction is implemented.
7. Confirm removing a dataset from the allowlist is an effective rollback step.

### Estimated Effort

| Task | Estimated time |
| --- | --- |
| Define configuration format and docs | 30-60 minutes |
| Implement allowlist parsing and enforcement for dataset-targeting tools | 0.5 day |
| Add unit tests and audit category tests | 0.5 day |
| Validate on Cloud Run with allowed and denied datasets | 30-60 minutes |
| Decide whether query-tool reference extraction is needed | 30-90 minutes |

Total estimate: about 1.0-2.0 days for metadata tools only, or longer if query SQL reference extraction is required.

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
| P2 | Complete | Consider project-scoped dataset allowlist. | Optional defense-in-depth; implement only when IAM is too broad or rollout policy needs a dataset kill switch. |

## Follow-Up Hardening Candidates

These are not required to complete the initial `ice-sh` rollout, but should be considered before broad multi-project use:

- Optional project-scoped dataset allowlist for deployments where IAM alone is not enough for operational policy.
- Implement BigQuery audit dataset export after retention and reporting requirements are confirmed.
- Query history UI for administrators after audit export and review requirements are confirmed.
- Dedicated runtime service account instead of the default compute service account.
- Persistent OAuth/session storage if Cloud Run restarts or session longevity become operational issues.

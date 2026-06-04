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

The following Phase 8 controls are implemented:

- `ALLOWED_PROJECT_IDS` environment variable.
- `ALLOWED_USER_EMAILS` environment variable.
- BigQuery tool calls for projects outside `ALLOWED_PROJECT_IDS` are rejected before BigQuery API calls.
- BigQuery tool calls from users outside `ALLOWED_USER_EMAILS` are rejected before BigQuery API calls.
- Rejected project calls are written to audit logs with `success=false` and `rejection_reason="project_not_allowed"`.
- Rejected user calls are written to audit logs with `success=false` and `rejection_reason="user_not_allowed"`.
- `list_projects` is filtered to allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Unit tests cover empty allowlists, allowed project, rejected project, default-project rejection, allowed user, rejected user, and case-insensitive email matching.
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
| Dataset allowlist | Use BigQuery IAM first. Grant `roles/bigquery.dataViewer` at dataset scope wherever possible. Add an application-side dataset allowlist only when operational policy requires a stricter boundary than IAM. | Dataset-level IAM is the source of truth and avoids duplicating access policy in the MCP service unless there is a clear control need. |
| User allowlist | Implemented with optional `ALLOWED_USER_EMAILS`. Keep it empty for normal domain+IAM operation; set it for sensitive deployments or limited pilots. | Keeps onboarding simple by default while supporting named-user restriction when needed. |
| Domain allowlist | Required. Initial value: `impress.co.jp`. | Blocks non-company Google accounts before BigQuery access is attempted. |
| Per-project policy | Required. Cloud Run, Artifact Registry, Secret Manager, WIF, deploy service account, GitHub Secrets, OAuth redirect URI, and health check must be managed per GCP project. | Keeps blast radius and deployment ownership clear. |
| BigQuery audit dataset | Follow-up hardening, not required for initial operation. Cloud Logging is required now. | Cloud Logging satisfies Phase 7 audit verification; BigQuery persistence can be added once retention/reporting requirements are clear. |
| Query history UI | Follow-up improvement, not required for initial operation. | Audit logs are enough for the initial controlled rollout. |
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

Recommended for:

- Small internal pilots.
- Closely related projects with the same administrators and IAM model.
- Temporary validation before splitting into dedicated deployments.

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

Planned environment variables:

```text
ALLOWED_DATASET_IDS=
```

Current behavior:

- Empty `ALLOWED_PROJECT_IDS` means no application-side project restriction beyond BigQuery IAM. This is acceptable only for narrow pilots.
- Non-empty `ALLOWED_PROJECT_IDS` rejects tool calls for projects outside the list before BigQuery API calls.
- `list_projects` returns only allowed projects when `ALLOWED_PROJECT_IDS` is set.
- Empty `ALLOWED_USER_EMAILS` means domain allowlist plus BigQuery IAM controls users.
- Non-empty `ALLOWED_USER_EMAILS` rejects tool calls from users outside the list before BigQuery API calls.
- Email matching for `ALLOWED_USER_EMAILS` is case-insensitive.
- Dataset allowlist remains planned and should be optional and scoped by project.

Security reason:

- Project allowlists reduce accidental cross-project query attempts.
- User allowlists help pilot sensitive deployments.
- Dataset allowlists are useful when operational policy is stricter than IAM, but they increase maintenance burden.

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
13. Unauthorized project or denied job creation returns an error, not a successful MCP response.
14. Cloud Logging records successful reads and failed/rejected attempts with `success`, `error`, `user_email`, `tool`, and `project_id`.

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

Initial retention stays in Cloud Logging. A BigQuery audit dataset can be added later if longer retention, reporting, or dashboarding is required.

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

## Phase 8 Implementation Backlog

The following backlog turns this policy into product controls:

| Priority | Status | Item | Purpose |
| --- | --- | --- | --- |
| P0 | Complete | Implement `ALLOWED_PROJECT_IDS` enforcement. | Prevent cross-project use from a shared deployment. |
| P0 | Complete | Add tests for allowed and rejected project IDs. | Prove allowlist behavior before broad rollout. |
| P1 | Complete | Implement optional `ALLOWED_USER_EMAILS`. | Support limited pilots and sensitive deployments. |
| P1 | Partial | Add audit fields for rejection reason category. | Project and user allowlist rejections are categorized; SQL guard and BigQuery API errors still need structured categories. |
| P1 | Open | Document per-project rollout template. | Make future rollouts repeatable. |
| P2 | Open | Evaluate BigQuery audit dataset export. | Support retention, reporting, and dashboards beyond Cloud Logging. |
| P2 | Open | Consider query history UI. | Give administrators a review surface without raw log browsing. |
| P2 | Open | Consider project-scoped dataset allowlist. | Add an application boundary when IAM is too broad for operational policy. |

## Follow-Up Hardening Candidates

These are not required to complete the initial `ice-sh` rollout, but should be considered before broad multi-project use:

- Optional dataset allowlist for deployments where IAM alone is not enough for operational policy.
- BigQuery audit dataset export.
- Query history UI for administrators.
- Dedicated runtime service account instead of the default compute service account.
- Persistent OAuth/session storage if Cloud Run restarts or session longevity become operational issues.

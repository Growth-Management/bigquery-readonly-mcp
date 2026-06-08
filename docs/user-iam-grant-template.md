# User IAM Grant Template

This document is an operator template for adding a Google account to the BigQuery Readonly MCP pilot or rollout.

The MCP server must continue to call BigQuery with the logged-in user's Google OAuth token. Do not grant broad BigQuery access to the Cloud Run runtime service account for query execution.

## When To Use

Use this template when adding a new user to an existing MCP rollout, such as the current `ice-mp` pilot.

Current pilot defaults:

| Field | Value |
| --- | --- |
| Cloud Run deployment project | `ice-sh` |
| Current BigQuery target project | `ice-mp` |
| Current MCP allowed project | `ice-mp` |
| Current MCP allowed users | `sinohara@impress.co.jp` |
| Session backend | `firestore` |
| Session TTL | `3600` seconds |

## Recommended Permission Model

Grant BigQuery access to the user or a dedicated Google Group, not to the MCP runtime service account.

Recommended minimum grants:

| Permission purpose | Recommended scope | Role |
| --- | --- | --- |
| Create query jobs | BigQuery project | `roles/bigquery.jobUser` |
| Read table metadata and data | Smallest practical dataset | `roles/bigquery.dataViewer` |

Prefer dataset-level `roles/bigquery.dataViewer`. Avoid project-wide `roles/bigquery.dataViewer` unless the project is explicitly intended for broad analysis access.

## Individual User Grant

Set variables:

```bash
PROJECT_ID="ice-mp"
DATASET_ID="ice_mp_datamart"
USER_EMAIL="user@example.com"
```

Grant job creation on the project:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$USER_EMAIL" \
  --role="roles/bigquery.jobUser"
```

Grant dataset read access:

```bash
bq update \
  --source <(bq show --format=prettyjson "$PROJECT_ID:$DATASET_ID" \
    | jq --arg member "$USER_EMAIL" '
      .access += [{"role":"READER","userByEmail":$member}]
    ') \
  "$PROJECT_ID:$DATASET_ID"
```

If process substitution is inconvenient in Cloud Shell, write the JSON to a temporary file instead:

```bash
bq show --format=prettyjson "$PROJECT_ID:$DATASET_ID" \
  | jq --arg member "$USER_EMAIL" '
    .access += [{"role":"READER","userByEmail":$member}]
  ' > /tmp/dataset-access.json

bq update --source /tmp/dataset-access.json "$PROJECT_ID:$DATASET_ID"
```

## Dedicated Google Group Grant

Use a dedicated Google Group when adding multiple users. Do not reuse a broad existing group unless its full membership is approved for the BigQuery datasets.

Set variables:

```bash
PROJECT_ID="ice-mp"
DATASET_ID="ice_mp_datamart"
GROUP_EMAIL="bigquery-mcp-ice-mp-users@example.com"
```

Grant job creation on the project:

```bash
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="group:$GROUP_EMAIL" \
  --role="roles/bigquery.jobUser"
```

Grant dataset read access:

```bash
bq show --format=prettyjson "$PROJECT_ID:$DATASET_ID" \
  | jq --arg member "$GROUP_EMAIL" '
    .access += [{"role":"READER","groupByEmail":$member}]
  ' > /tmp/dataset-access.json

bq update --source /tmp/dataset-access.json "$PROJECT_ID:$DATASET_ID"
```

## MCP User Allowlist Update

If `ALLOWED_USER_EMAILS` is set, add the user to the Cloud Run environment and GitHub Actions deploy defaults.

For a temporary Cloud Run update:

```bash
gcloud run services update bigquery-readonly-mcp \
  --project ice-sh \
  --region asia-northeast1 \
  --update-env-vars ALLOWED_USER_EMAILS="sinohara@impress.co.jp,user@example.com"
```

Then update `.github/workflows/deploy-cloud-run.yml` so the next deploy preserves the same value.

If switching from named users to IAM-only user control for a rollout, set `ALLOWED_USER_EMAILS=` only after the security owner accepts that all users in `impress.co.jp` with BigQuery IAM may use the MCP for the allowed projects.

## Validation

After adding the user, validate with the user's own Google login.

1. Reconnect the MCP client and complete Google OAuth login.
2. Run `list_datasets` for the allowed project.
3. Run `list_tables` and `get_table_schema` for an allowed dataset/table.
4. Run a bounded `dry_run_query`.
5. Run a bounded `run_readonly_query`.
6. Confirm a project outside `ALLOWED_PROJECT_IDS` is rejected.
7. Confirm Cloud Logging contains the user's `user_email` and the expected `project_id`.

Example Cloud Logging filter:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.user_email="user@example.com"
```

## Rollback

To remove access:

1. Remove the user from `ALLOWED_USER_EMAILS`, when configured.
2. Remove the user's BigQuery project IAM binding or remove them from the dedicated Google Group.
3. Remove direct dataset access entries if individual dataset access was granted.
4. Ask the user to disconnect the MCP client or invalidate their session by rotating access as needed.
5. Confirm rejected calls are logged with `user_not_allowed` or BigQuery IAM denial.

## Safety Notes

- Application allowlists never grant BigQuery access. They only add restrictions before BigQuery API calls.
- BigQuery IAM remains the source of truth for what each Google account may read.
- Dedicated Google Groups are safer than broad existing groups for multi-user rollout.
- Keep validation output small and avoid exposing company-sensitive data during smoke tests.

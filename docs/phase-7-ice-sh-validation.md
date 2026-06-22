# Phase 7: ice-sh Validation Record

Date: 2026-06-01 through 2026-06-04
Environment: Cloud Run `bigquery-readonly-mcp` in project `ice-sh`, region `asia-northeast1`
User identity: `sinohara@impress.co.jp`

## Summary

Phase 7 is complete for OAuth, MCP connectivity, BigQuery readonly tools, SQL guard behavior, unauthorized project rejection, and Cloud Logging audit output.

The final Access Denied validation was completed on 2026-06-04 using project `bq-mcp-access-denied-test-2`. A project-level IAM Deny policy denied `sinohara@impress.co.jp` BigQuery job creation, and MCP `dry_run_query` returned HTTP `403 Forbidden`. Cloud Logging also recorded the denied tool call with `success=false`.

On 2026-06-22, Phase 4 audit log hardening was revalidated from Cloud Shell after PR #10 added BigQuery Job `statistics.query.referencedTables` extraction. Cloud Logging now records `referenced_tables` and `referenced_table_count` for completed query job audit events, and fills top-level `dataset` / `table` when exactly one referenced table is present.

## Completed Checks

| Check | Status | Evidence |
| --- | --- | --- |
| OAuth login | Complete | Browser login produced an `mcp_session` cookie and authenticated `/mcp` calls succeeded. |
| MCP authenticated tool call | Complete | Direct JSON-RPC `tools/call` to `/mcp` with `mcp_session` succeeded. |
| `list_projects` | Complete | Returned visible projects including `ice-sh`. |
| `list_datasets` | Complete | Returned datasets from `ice-sh`, including `ice_sh_datamart`. |
| `list_tables` | Complete | Returned `ice_sh_datamart.sh_digital_margaret_datamart_for_data_portal`. |
| `get_table_schema` | Complete | Returned schema and `num_rows=2002` for the validation table. |
| `dry_run_query` | Complete | Returned `total_bytes_processed=140956` and `maximum_bytes_billed=1073741824`. |
| `run_readonly_query` | Complete | Returned 5 rows from the validation table. |
| DML rejection | Complete | `DELETE` was rejected with `Only SELECT or WITH queries are allowed`. |
| DDL rejection | Complete | `CREATE TABLE` was rejected with `Only SELECT or WITH queries are allowed`. |
| Audit log | Complete | Cloud Logging contains `bigquery_mcp_tool_call` entries for success, SQL guard rejection, unauthorized project rejection, and referenced table logging cases. |
| Referenced table audit fields | Complete | Cloud Logging recorded `referenced_tables`, `referenced_table_count`, `dataset`, `table`, and `bytes_processed` for query job status/result audit events. |
| Unauthorized project rejection | Complete | `dry_run_query` against `bq-mcp-access-denied-test-2` returned HTTP `403 Forbidden`; Cloud Logging recorded `success=false`. |

## Validation Dataset And Table

Dataset:

```text
ice-sh.ice_sh_datamart
```

Table:

```text
ice-sh.ice_sh_datamart.sh_digital_margaret_datamart_for_data_portal
```

Schema fields observed:

- `date` (`DATE`)
- `user_type` (`STRING`)
- `contents_title` (`STRING`)
- `file_title` (`STRING`)
- `release_date` (`DATE`)
- `sum_pageviews_7days` (`INTEGER`)
- `sum_users_7days` (`INTEGER`)
- `exits_rate_7days` (`NUMERIC`)
- `sum_pageviews_30days` (`INTEGER`)
- `sum_users_30days` (`INTEGER`)
- `exits_rate_30days` (`NUMERIC`)
- `sum_pageviews_60days` (`INTEGER`)
- `sum_users_60days` (`INTEGER`)
- `exits_rate_60days` (`NUMERIC`)

## Successful Readonly Query

```sql
SELECT date, user_type, contents_title, sum_pageviews_7days
FROM `ice-sh.ice_sh_datamart.sh_digital_margaret_datamart_for_data_portal`
LIMIT 5
```

Dry run result:

```text
total_bytes_processed: 140956
maximum_bytes_billed: 1073741824
```

Execution result:

```text
returned_rows: 5
row_count: 5
total_bytes_processed: 140956
total_bytes_billed: 10485760
```

## SQL Guard Evidence

DML probe:

```sql
DELETE FROM `ice-sh.ice_sh_datamart.sh_digital_margaret_datamart_for_data_portal` WHERE TRUE
```

Result:

```text
JSON-RPC error code: -32000
message: Only SELECT or WITH queries are allowed
```

DDL probe:

```sql
CREATE TABLE `ice-sh.ice_sh_datamart.mcp_validation_tmp` AS SELECT 1 AS id
```

Result:

```text
JSON-RPC error code: -32000
message: Only SELECT or WITH queries are allowed
```

These checks confirm that write-oriented SQL is rejected by the MCP SQL guard before BigQuery execution.

## Unauthorized Project Evidence

Validation project:

```text
bq-mcp-access-denied-test-2
```

Deny policy:

```text
policy_id: deny-bq-sinohara-for-mcp-validation
display_name: Deny BigQuery access for MCP validation
denied_principal: principal://goog/subject/sinohara@impress.co.jp
```

Denied permissions:

```text
bigquery.googleapis.com/datasets.get
bigquery.googleapis.com/tables.list
bigquery.googleapis.com/tables.get
bigquery.googleapis.com/tables.getData
bigquery.googleapis.com/jobs.create
```

Probe query:

```sql
SELECT 1 AS access_denied_probe
```

MCP tool call:

```text
dry_run_query(project_id="bq-mcp-access-denied-test-2", sql="SELECT 1 AS access_denied_probe")
```

Result:

```text
JSON-RPC error code: -32000
message: Client error '403 Forbidden' for url 'https://bigquery.googleapis.com/bigquery/v2/projects/bq-mcp-access-denied-test-2/queries'
```

This confirms that BigQuery execution follows the logged-in user's effective IAM and that unauthorized project access is not treated as a successful MCP response.

## Audit Log Evidence

Cloud Logging filter used:

```bash
gcloud logging read \
'resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"' \
--project ice-sh \
--limit 20 \
--format=json
```

Observed audit fields:

- `user_email`: `sinohara@impress.co.jp`
- `tool`: `list_projects`, `list_datasets`, `list_tables`, `get_table_schema`, `dry_run_query`, `run_readonly_query`
- `project_id`: `ice-sh` and validation project IDs
- `success`: `true` for successful reads, `false` for rejected SQL and unauthorized project access
- `error`: rejection reason such as `Only SELECT or WITH queries are allowed` or HTTP `403 Forbidden`

Unauthorized project audit evidence:

```text
timestamp: 2026-06-04T06:22:24.420190Z
user_email: sinohara@impress.co.jp
tool: dry_run_query
project_id: bq-mcp-access-denied-test-2
success: false
error: Client error '403 Forbidden' for url 'https://bigquery.googleapis.com/bigquery/v2/projects/bq-mcp-access-denied-test-2/queries'
```

This confirms that both successful tool calls and rejected tool calls are auditable in Cloud Logging.

## Referenced Table Audit Evidence

Validation date: 2026-06-22
Validation project: `jumpplus-4a5f4`
Cloud Run project: `ice-sh`
User identity: `sinohara@impress.co.jp`
PR: https://github.com/Growth-Management/bigquery-readonly-mcp/pull/10
Merge commit: `9d77a874e35f15e5bda855c1331c06dbe12a9916`

Validation query job:

```text
job_id: job_cRKZjINLqaesYyJKa3-KKXcaS8wx
location: US
```

Referenced table:

```text
jumpplus-4a5f4.dataset_temp_aggregation.aggr_coin_balances
```

Cloud Shell filter used:

```bash
gcloud logging read \
  'jsonPayload.event_type="bigquery_mcp_tool_call" AND jsonPayload.job_id="job_cRKZjINLqaesYyJKa3-KKXcaS8wx"' \
  --project="ice-sh" \
  --freshness=2h \
  --limit=10 \
  --format=json | jq '.[].jsonPayload | {tool, project_id, dataset, table, referenced_tables, referenced_table_count, bytes_processed, success, error}'
```

Observed `get_query_job_status` audit payload:

```json
{
  "tool": "get_query_job_status",
  "project_id": "jumpplus-4a5f4",
  "dataset": "dataset_temp_aggregation",
  "table": "aggr_coin_balances",
  "referenced_tables": [
    {
      "dataset_id": "dataset_temp_aggregation",
      "full_table_id": "jumpplus-4a5f4.dataset_temp_aggregation.aggr_coin_balances",
      "project_id": "jumpplus-4a5f4",
      "table_id": "aggr_coin_balances"
    }
  ],
  "referenced_table_count": 1,
  "bytes_processed": 99792,
  "success": true,
  "error": null
}
```

Observed `fetch_query_job_results` audit payload:

```json
{
  "tool": "fetch_query_job_results",
  "project_id": "jumpplus-4a5f4",
  "dataset": "dataset_temp_aggregation",
  "table": "aggr_coin_balances",
  "referenced_tables": [
    {
      "dataset_id": "dataset_temp_aggregation",
      "full_table_id": "jumpplus-4a5f4.dataset_temp_aggregation.aggr_coin_balances",
      "project_id": "jumpplus-4a5f4",
      "table_id": "aggr_coin_balances"
    }
  ],
  "referenced_table_count": 1,
  "bytes_processed": 99792,
  "success": true,
  "error": null
}
```

Observed `start_readonly_query_job` audit payload:

```json
{
  "tool": "start_readonly_query_job",
  "project_id": "jumpplus-4a5f4",
  "dataset": null,
  "table": null,
  "referenced_tables": null,
  "referenced_table_count": null,
  "bytes_processed": 0,
  "success": true,
  "error": null
}
```

The `start_readonly_query_job` entry is expected to have empty referenced table fields when BigQuery has not yet populated completed query statistics. The completed `get_query_job_status` and `fetch_query_job_results` entries confirm that referenced table metadata is now auditable after job completion.

## Recommended Next Steps

1. Preserve this document as the Phase 7 validation record.
2. Keep the `bq-mcp-access-denied-test-2` Deny policy only as long as needed for audit evidence or repeat validation.
3. Move to Phase 8 planning for rollout policy, allowlists, audit retention, and query history.

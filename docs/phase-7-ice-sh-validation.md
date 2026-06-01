# Phase 7: ice-sh Validation Record

Date: 2026-06-01
Environment: Cloud Run `bigquery-readonly-mcp` in project `ice-sh`, region `asia-northeast1`
User identity: `sinohara@impress.co.jp`

## Summary

Phase 7 is functionally complete for OAuth, MCP connectivity, BigQuery readonly tools, SQL guard behavior, and Cloud Logging audit output.

One item remains open: validating that an existing project outside the logged-in user's IAM scope returns `403` / `Access Denied`. A non-accessible project probe returned a JSON-RPC error, but the underlying BigQuery response was `404 Project not found`, so it is not strong enough evidence for the Access Denied case.

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
| Audit log | Complete | Cloud Logging contains `bigquery_mcp_tool_call` entries for success and rejection cases. |
| Unauthorized project Access Denied | Open | Needs an existing project ID that is not visible to the logged-in user. |

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
- `project_id`: `ice-sh` and probe project IDs
- `success`: `true` for successful reads, `false` for rejected SQL
- `error`: rejection reason such as `Only SELECT or WITH queries are allowed`

This confirms that both successful tool calls and SQL guard rejections are auditable in Cloud Logging.

## Open Item: Unauthorized Project Access Denied

Current status: open.

A probe against `google.com:cloud-bigtable-public-data` returned a JSON-RPC error, but the BigQuery API response was:

```text
404 Not found: Project google.com:cloud-bigtable-public-data
```

This proves the MCP does not turn an inaccessible project probe into a successful tool response, but it does not prove the stricter `403` / `Access Denied` behavior.

To close this item, identify an existing project ID that is not returned by `list_projects` for the logged-in user, then run:

```bash
UNAUTHORIZED_PROJECT="replace-with-existing-project-without-access"

curl -sS -X POST "$CLOUD_RUN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Cookie: mcp_session=$MCP_SESSION" \
  -d "{
    \"jsonrpc\":\"2.0\",
    \"id\":111,
    \"method\":\"tools/call\",
    \"params\":{
      \"name\":\"list_datasets\",
      \"arguments\":{
        \"project_id\":\"$UNAUTHORIZED_PROJECT\"
      }
    }
  }" | jq .
```

Expected result:

```text
JSON-RPC error with 403, Access Denied, or Permission denied in the message
```

Then confirm the failed call is also recorded in Cloud Logging with `success=false`.

## Recommended Next Steps

1. Keep the unauthorized-project Access Denied check open until a real no-access project ID is available.
2. Move to Phase 8 planning in parallel, because the remaining open item does not block the validated readonly path for `ice-sh`.
3. When the Access Denied project ID is available, run the one-command check above and update this document.

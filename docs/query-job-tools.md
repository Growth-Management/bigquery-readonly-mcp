# BigQuery Job API Query Tools

This MCP keeps the existing synchronous `run_readonly_query` tool for short reads and adds Job API based tools for longer validation queries.

Use the Job API flow for 30-day or 180-day source/destination comparison queries that may fail on the synchronous BigQuery query endpoint before the SQL itself is the problem.

## Tools

### `start_readonly_query_job`

Starts a BigQuery query job with `jobs.insert`.

Inputs:

- `project_id`
- `sql`
- `location` optional
- `maximum_bytes_billed` optional
- `job_labels` optional
- `dry_run` optional, default `false`
- `use_query_cache` optional

Behavior:

- Only one readonly `SELECT` or `WITH` statement is accepted.
- Comments, string literals, and quoted identifiers are masked before forbidden keywords are checked.
- DDL, DML, BigQuery scripting, and multiple statements are rejected before BigQuery is called.
- `maximum_bytes_billed` defaults to `MAXIMUM_BYTES_BILLED`.
- `job_labels` can carry audit context such as `audit_target=38079` or a datamart id.
- `dry_run=true` uses a dry run and does not create a query job.

Example:

```json
{
  "project_id": "ice-sh",
  "location": "asia-northeast1",
  "sql": "WITH source AS (SELECT id, coin_type, updated_at FROM `ice-sh.hatena__warehouse__giga_to_raise.pay_coin_charge_histories_all` UNION ALL SELECT id, coin_type, updated_at FROM `ice-sh.hatena__warehouse__giga_to_raise.bonus_coin_charge_histories_all`), dest AS (SELECT id, coin_type, updated_at FROM `ice-sh.dataset_aggregation_tables.raise_coin_charge_histories`) SELECT COUNTIF(dest.id IS NULL) AS missing_in_dest_keys, COUNTIF(source.id IS NULL) AS extra_in_dest_keys, COUNTIF(source.updated_at != dest.updated_at) AS updated_at_mismatch_keys FROM source FULL OUTER JOIN dest USING (id, coin_type)",
  "maximum_bytes_billed": 1073741824,
  "job_labels": {
    "audit_target": "38079",
    "datamart_id": "raise_coin_charge_histories"
  },
  "use_query_cache": false
}
```

Response includes:

- `job_id`
- `project_id`
- `location`
- `state`
- `created_at`
- `started_at`
- `ended_at`
- `total_bytes_processed`
- `total_bytes_billed`
- `cache_hit`
- `errorResult`
- `errors`

### `get_query_job_status`

Fetches query job status with `jobs.get`.

Inputs:

- `project_id`
- `job_id`
- `location` optional

Use this for polling until `state` is `DONE`. If BigQuery finishes the job with an error, inspect `errorResult` and `errors`.

### `fetch_query_job_results`

Fetches one bounded result page with `jobs.getQueryResults`.

Inputs:

- `project_id`
- `job_id`
- `location` optional
- `page_token` optional
- `max_results` optional

`max_results` is capped by the server-side `MAX_RESULTS` setting so the MCP does not return huge result pages. Use `next_page_token` to fetch another page.

### `cancel_query_job`

Cancels a long-running query job with `jobs.cancel`.

Inputs:

- `project_id`
- `job_id`
- `location` optional

## Recommended Flow

1. Call `start_readonly_query_job` with `dry_run=true` to check estimated bytes.
2. Call `start_readonly_query_job` with `dry_run=false` and useful `job_labels`.
3. Poll `get_query_job_status` until `state` is `DONE`.
4. If `errorResult` is present, inspect it directly instead of treating it as a generic HTTP 400.
5. Call `fetch_query_job_results` with a small `max_results` value.
6. Continue with `next_page_token` only when more result rows are needed.
7. Call `cancel_query_job` if the query is no longer needed or was started with the wrong parameters.

## Required BigQuery Permissions

- `bigquery.jobs.create`
- `bigquery.jobs.get`
- `bigquery.tables.getData`
- `bigquery.tables.get`

Future destination-table or temporary-table workflows would require separate review before adding permissions such as:

- `bigquery.tables.create`
- `bigquery.tables.updateData`
- `bigquery.tables.delete`

Those permissions are not required for the current readonly Job API flow.

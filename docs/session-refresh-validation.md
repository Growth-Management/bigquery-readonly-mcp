# Refresh-backed session validation

This document records the validation path for making the BigQuery Readonly MCP practical beyond the roughly 1-hour Google access-token lifetime.

## Goal

- Keep BigQuery execution bound to the logged-in user's Google OAuth identity and IAM.
- Store OAuth tokens only as encrypted Firestore session data.
- Allow a practical MCP session TTL, initially 24 hours, without requiring hourly reconnects.
- Preserve explicit re-login fallback when Google rejects refresh or the session expires.

## Runtime settings

Expected pilot settings after deploy:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=86400
OAUTH_REFRESH_WINDOW_SECONDS=300
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
ALLOWED_PROJECT_IDS=
ALLOWED_DATASET_IDS=
```

`ALLOWED_PROJECT_IDS` and `ALLOWED_DATASET_IDS` are intentionally empty for the approved pilot. Project and dataset access are governed by the authenticated user's BigQuery IAM.

## Implementation behavior

- `/oauth/authorize` requests Google OAuth with `access_type=offline` and `include_granted_scopes=true`.
- Newly created Firestore sessions store:
  - `email`
  - application session `expires_at`
  - Google access-token `access_token_expires_at`
  - encrypted access token
  - encrypted refresh token, when Google returns one
- When a session is read and the access token is within `OAUTH_REFRESH_WINDOW_SECONDS` of expiry, the server exchanges the refresh token for a new access token and updates Firestore.
- If the refresh token is missing, invalid, revoked, or undecryptable after the access token has expired, the session is deleted and the user must reconnect.

## Validation sequence

### 1. Confirm GitHub Actions deploy

```bash
gh run list --repo Growth-Management/bigquery-readonly-mcp --limit 5
```

Expected: the deploy run for the refresh-token session commits is successful.

### 2. Confirm Cloud Run env

```bash
gcloud run services describe bigquery-readonly-mcp \
  --project ice-sh \
  --region asia-northeast1 \
  --format=json | jq -r '
    .spec.template.spec.containers[0].env[]
    | select(.name=="SESSION_STORE_BACKEND"
      or .name=="FIRESTORE_SESSION_COLLECTION"
      or .name=="SESSION_TTL_SECONDS"
      or .name=="OAUTH_REFRESH_WINDOW_SECONDS"
      or .name=="ALLOWED_PROJECT_IDS"
      or .name=="ALLOWED_DATASET_IDS"
      or .name=="ALLOWED_USER_EMAILS")
    | "\(.name)=\(.value)"
  '
```

Expected:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=86400
OAUTH_REFRESH_WINDOW_SECONDS=300
ALLOWED_PROJECT_IDS=
ALLOWED_DATASET_IDS=
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
```

### 3. Reconnect ChatGPT MCP once

Existing sessions created before refresh-token support may not contain a refresh token. Reconnect the MCP connector once after deployment so a new Firestore session is created through the offline OAuth flow.

Expected: Google consent/account selection appears. After connecting, MCP tool calls should work.

### 4. Confirm Firestore document shape

```bash
ACCESS_TOKEN="$(gcloud auth print-access-token)"

curl -sS \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  "https://firestore.googleapis.com/v1/projects/ice-sh/databases/(default)/documents/bigquery_mcp_sessions?pageSize=5" \
  | jq '.documents[] | {
      name,
      fields: (.fields | keys),
      email: .fields.email.stringValue,
      expires_at: .fields.expires_at,
      access_token_expires_at: .fields.access_token_expires_at,
      has_access_token_ciphertext: (.fields.access_token_ciphertext != null),
      has_refresh_token_ciphertext: (.fields.refresh_token_ciphertext != null)
    }'
```

Expected: a recent document for `sinohara@impress.co.jp` has both `access_token_ciphertext` and `refresh_token_ciphertext`. Token plaintext must never be printed or stored in docs.

### 5. Confirm metadata and query execution

Use ChatGPT MCP or Cloud Shell with the current session and run:

```bash
export CLOUD_RUN_URL="https://bigquery-readonly-mcp-ppwdcgrska-an.a.run.app"

curl -sS -X POST "$CLOUD_RUN_URL/mcp" \
  -H "Content-Type: application/json" \
  -H "Cookie: mcp_session=$MCP_SESSION" \
  -d '{
    "jsonrpc":"2.0",
    "id":901,
    "method":"tools/call",
    "params":{
      "name":"run_readonly_query",
      "arguments":{
        "project_id":"ice-mp",
        "max_results":5,
        "sql":"SELECT 1 AS refresh_session_probe"
      }
    }
  }' | jq .
```

Expected: `run_readonly_query` succeeds with one row. This proves the MCP can execute a readonly query, not only list metadata.

### 6. Confirm audit log

```bash
gcloud logging read \
'resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.tool="run_readonly_query"' \
--project ice-sh \
--limit 5 \
--format=json | jq '.[] | {
  timestamp,
  user_email: .jsonPayload.user_email,
  tool: .jsonPayload.tool,
  project_id: .jsonPayload.project_id,
  success: .jsonPayload.success,
  rejection_reason: .jsonPayload.rejection_reason,
  error: .jsonPayload.error
}'
```

Expected: recent `run_readonly_query` event for `sinohara@impress.co.jp` with `success=true`.

### 7. Confirm 1-hour-plus behavior

After at least 65 minutes from reconnect, run the same `run_readonly_query` probe again.

Expected: the query still succeeds without manual reconnect. This proves access-token refresh is working. If it fails with login required or invalid credentials, reconnect once and inspect whether the Firestore document has `refresh_token_ciphertext`.

## Rollback

To revert to the previous short-session behavior:

```bash
gcloud run services update bigquery-readonly-mcp \
  --project ice-sh \
  --region asia-northeast1 \
  --update-env-vars SESSION_TTL_SECONDS=3600,OAUTH_REFRESH_WINDOW_SECONDS=300
```

If token storage must be disabled entirely, set `SESSION_STORE_BACKEND=memory`. This will make sessions instance-local and vulnerable to Cloud Run restarts, so use only as an emergency rollback.

## Open follow-up

- Decide whether 24 hours is the long-term session TTL or whether 8-12 business hours is preferable.
- Decide whether administrators need a documented process for revoking refresh-backed MCP sessions by deleting Firestore documents.
- Confirm whether ChatGPT connector token caching honors the 24-hour MCP bearer TTL exactly or reconnects earlier.

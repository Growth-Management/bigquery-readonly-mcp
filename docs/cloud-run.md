# Cloud Run Deployment Guide

This guide covers the Phase 5 Cloud Run setup for `Growth-Management/bigquery-readonly-mcp`.

## Fixed Defaults

- Deploy project: `ice-sh`
- Region: `asia-northeast1`
- Service: `bigquery-readonly-mcp`
- Initial BigQuery validation project: `ice-sh`
- Current pilot BigQuery project: `ice-mp`
- Allowed domain: `impress.co.jp`

Deployment resources are managed per GCP project. For the initial rollout, deploy into `ice-sh`. For another project, repeat this guide with that project ID and keep its Cloud Run, Artifact Registry, Secret Manager, OAuth redirect URL, GitHub Secrets, and optional Firestore session storage separate.

## Required APIs

Enable these APIs in `ice-sh`:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iamcredentials.googleapis.com \
  firestore.googleapis.com \
  --project ice-sh
```

Firestore is required for the current pilot session backend.

## Artifact Registry

Create a Docker repository for the Cloud Run image:

```bash
gcloud artifacts repositories create bigquery-readonly-mcp \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="BigQuery readonly MCP images" \
  --project ice-sh
```

## Secret Manager

Store secret values in Secret Manager. Do not put secret values in GitHub or `env.example.yaml`.

```bash
printf '%s' '<oauth-client-id>' | gcloud secrets create google-oauth-client-id \
  --data-file=- \
  --project ice-sh

printf '%s' '<oauth-client-secret>' | gcloud secrets create google-oauth-client-secret \
  --data-file=- \
  --project ice-sh

openssl rand -base64 32 | gcloud secrets create bigquery-mcp-session-secret \
  --data-file=- \
  --project ice-sh
```

If a secret already exists, add a new version instead:

```bash
printf '%s' '<new-value>' | gcloud secrets versions add google-oauth-client-secret \
  --data-file=- \
  --project ice-sh
```

## OAuth Redirect URI

Create a Google OAuth Web application in `ice-sh`, then register the deployed callback URL:

```text
https://<cloud-run-url>/oauth/callback
```

Scopes:

- `openid`
- `email`
- `profile`
- `https://www.googleapis.com/auth/bigquery.readonly`

## Manual Deploy

Use this path for a first manual smoke test before relying on GitHub Actions.

```bash
gcloud auth configure-docker asia-northeast1-docker.pkg.dev --quiet

IMAGE="asia-northeast1-docker.pkg.dev/ice-sh/bigquery-readonly-mcp/bigquery-readonly-mcp:manual-$(date +%Y%m%d%H%M%S)"

docker build -t "$IMAGE" .
docker push "$IMAGE"

gcloud run deploy bigquery-readonly-mcp \
  --image "$IMAGE" \
  --region asia-northeast1 \
  --project ice-sh \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BASE_URL=https://<cloud-run-url>,ALLOWED_DOMAIN=impress.co.jp,DEFAULT_PROJECT_ID=ice-mp,ALLOWED_PROJECT_IDS=ice-mp,ALLOWED_DATASET_IDS=,ALLOWED_USER_EMAILS=sinohara@impress.co.jp,MAXIMUM_BYTES_BILLED=1073741824,MAX_RESULTS=1000,QUERY_TIMEOUT_SECONDS=60,SESSION_STORE_BACKEND=firestore,FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions,SESSION_TTL_SECONDS=3600" \
  --set-secrets "GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,SESSION_SECRET=bigquery-mcp-session-secret:latest"
```

After the first deploy, update `BASE_URL` to the actual Cloud Run URL and redeploy if needed. The OAuth redirect URI must match the same URL.

For the preferred GitHub Actions deployment path, see [`github-actions-deploy.md`](github-actions-deploy.md). The current GitHub Actions deploy defaults pin Firestore session persistence and `SESSION_TTL_SECONDS=3600`.

## Persistent Session Storage

Current pilot behavior uses Firestore-backed sessions:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=3600
```

Validation completed on 2026-06-08:

- Firestore API was enabled in `ice-sh`.
- Firestore database `(default)` exists in `asia-northeast1` using Firestore Native mode.
- Cloud Run runtime service account `635067190197-compute@developer.gserviceaccount.com` has `roles/datastore.user`.
- A session document was created in `bigquery_mcp_sessions`.
- The document contained `email`, `expires_at`, `nonce`, and `access_token_ciphertext`.
- The access token was not stored in plaintext.
- The same `mcp_session` worked after Cloud Run revision updates and after GitHub Actions deployment.

Security behavior:

- Access tokens are encrypted before being stored in Firestore.
- Encryption uses AES-GCM with a key derived from `SESSION_SECRET`.
- `SESSION_SECRET` rotation intentionally invalidates existing persisted sessions.
- Invalid or undecryptable session documents are deleted and treated as logged out.
- Firestore persistence does not grant BigQuery access. BigQuery calls still use the logged-in user's OAuth token and IAM permissions.

Operational limit:

- The server currently stores Google access tokens, not refresh tokens.
- Longer application session TTLs can outlive the Google access token and produce BigQuery `401` errors.
- `SESSION_TTL_SECONDS=86400` was tested and exposed this limitation.
- The current safe operating value is `SESSION_TTL_SECONDS=3600`.
- Longer session continuity requires refresh-token support and encrypted refresh-token storage.

Short-lived OAuth authorization requests and authorization codes remain in memory, so a login flow that overlaps a revision restart may still need to be retried. Already-created Firestore MCP sessions are not affected by this.

To confirm current Cloud Run settings:

```bash
gcloud run services describe bigquery-readonly-mcp \
  --project ice-sh \
  --region asia-northeast1 \
  --format=json | jq -r '
    .spec.template.spec.containers[0].env[]
    | select(.name=="SESSION_STORE_BACKEND" or .name=="FIRESTORE_SESSION_COLLECTION" or .name=="SESSION_TTL_SECONDS")
    | "\(.name)=\(.value)"
  '
```

Expected output:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=3600
```

## Health Check

Cloud Run reserves `/healthz` before the request reaches the container, so use `/health` for external service checks.

```bash
curl -fsS "https://<cloud-run-url>/health"
```

Expected response:

```json
{"status":"ok"}
```

You can also use the helper script:

```bash
scripts/check-healthz.sh "https://<cloud-run-url>"
```

## Secret Access For Runtime

The Cloud Run runtime service account needs `roles/secretmanager.secretAccessor` on these secrets:

- `google-oauth-client-id`
- `google-oauth-client-secret`
- `bigquery-mcp-session-secret`

For Firestore-backed session storage, the same runtime service account also needs Firestore document read/write/delete permissions. The current pilot uses `roles/datastore.user`.

The deploy service account needs deployment permissions only. It is not used to run BigQuery queries for users.

## Audit Log Check

After invoking a tool, confirm Cloud Logging has the JSON audit event:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
```

For the current pilot project:

```text
jsonPayload.project_id="ice-mp"
```

## Phase 5 Done Criteria

- Cloud Run service deploy succeeds.
- `https://<cloud-run-url>/health` returns `{"status":"ok"}`.
- HTTPS endpoint is registered as OAuth redirect URI.
- Secret values are supplied from Secret Manager.
- Cloud Logging receives app logs from the service.
- Firestore-backed MCP session storage is enabled.
- A logged-in MCP session survives a Cloud Run restart or new revision within the access-token-aware TTL.

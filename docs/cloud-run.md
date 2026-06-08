# Cloud Run Deployment Guide

This guide covers the Phase 5 Cloud Run setup for `Growth-Management/bigquery-readonly-mcp`.

## Fixed Defaults

- Deploy project: `ice-sh`
- Region: `asia-northeast1`
- Service: `bigquery-readonly-mcp`
- Initial BigQuery validation project: `ice-sh`
- Allowed domain: `impress.co.jp`

Deployment resources are managed per GCP project. For the initial rollout, deploy into `ice-sh`. For another project, repeat this guide with that project ID and keep its Cloud Run, Artifact Registry, Secret Manager, OAuth redirect URL, and GitHub Secrets separate.

## Required APIs

Enable these APIs in `ice-sh`:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iamcredentials.googleapis.com \
  --project ice-sh
```

If persistent sessions are enabled, also enable Firestore:

```bash
gcloud services enable firestore.googleapis.com --project ice-sh
```

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
  --set-env-vars "BASE_URL=https://<cloud-run-url>,ALLOWED_DOMAIN=impress.co.jp,DEFAULT_PROJECT_ID=ice-sh,MAXIMUM_BYTES_BILLED=1073741824,MAX_RESULTS=1000,QUERY_TIMEOUT_SECONDS=60" \
  --set-secrets "GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,SESSION_SECRET=bigquery-mcp-session-secret:latest"
```

After the first deploy, update `BASE_URL` to the actual Cloud Run URL and redeploy if needed. The OAuth redirect URI must match the same URL.

For the preferred GitHub Actions deployment path, see [`github-actions-deploy.md`](github-actions-deploy.md).

## Persistent Session Storage

Default behavior uses in-memory sessions:

```text
SESSION_STORE_BACKEND=memory
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
SESSION_TTL_SECONDS=3600
```

With the memory backend, an existing `mcp_session` cookie can stop working when Cloud Run creates a new instance, restarts, or deploys a new revision. This is safe but inconvenient because the user must login again.

Optional persistent sessions use Firestore:

```text
SESSION_STORE_BACKEND=firestore
FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions
```

When Firestore is enabled, only the post-login MCP session is persisted. Short-lived OAuth authorization requests and authorization codes remain in memory, so a login flow that overlaps a revision restart may still need to be retried.

Security behavior:

- Access tokens are encrypted before being stored in Firestore.
- Encryption uses AES-GCM with a key derived from `SESSION_SECRET`.
- `SESSION_SECRET` rotation intentionally invalidates existing persisted sessions.
- Invalid or undecryptable session documents are deleted and treated as logged out.
- Firestore persistence does not grant BigQuery access. BigQuery calls still use the logged-in user's OAuth token and IAM permissions.

Enablement checklist:

1. Enable `firestore.googleapis.com` in the Cloud Run deployment project.
2. Create or confirm a Firestore database in the deployment project.
3. Grant the Cloud Run runtime service account Firestore document read/write/delete permissions. Use `roles/datastore.user` unless a narrower custom role is available.
4. Set `SESSION_STORE_BACKEND=firestore` on Cloud Run.
5. Keep `FIRESTORE_SESSION_COLLECTION=bigquery_mcp_sessions` unless a different collection is needed.
6. Decide whether `SESSION_TTL_SECONDS=3600` is enough or whether a longer pilot value such as `86400` is acceptable.
7. Login once, invoke `/mcp`, deploy or restart a revision, then invoke `/mcp` again with the same cookie to confirm the session survives.

The current workflow keeps `SESSION_STORE_BACKEND=memory` until Firestore setup and restart validation are completed.

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

The deploy service account needs deployment permissions only. It is not used to run BigQuery queries for users.

## Audit Log Check

After invoking a tool, confirm Cloud Logging has the JSON audit event:

```text
resource.type="cloud_run_revision"
resource.labels.service_name="bigquery-readonly-mcp"
jsonPayload.event_type="bigquery_mcp_tool_call"
```

For the initial project:

```text
jsonPayload.project_id="ice-sh"
```

## Phase 5 Done Criteria

- Cloud Run service deploy succeeds.
- `https://<cloud-run-url>/health` returns `{"status":"ok"}`.
- HTTPS endpoint is registered as OAuth redirect URI.
- Secret values are supplied from Secret Manager.
- Cloud Logging receives app logs from the service.
- If Firestore sessions are enabled, a logged-in MCP session survives a Cloud Run restart or new revision until `SESSION_TTL_SECONDS` expires.

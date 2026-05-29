# Cloud Run Deployment Guide

This guide covers the Phase 5 Cloud Run setup for `Growth-Management/bigquery-readonly-mcp`.

## Fixed Defaults

- Deploy project: `bigquery-mcp-prod`
- Region: `asia-northeast1`
- Service: `bigquery-readonly-mcp`
- Initial BigQuery validation project: `ice-sh`
- Allowed domain: `impress.co.jp`

## Required APIs

Enable these APIs in `bigquery-mcp-prod`:

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  iamcredentials.googleapis.com \
  --project bigquery-mcp-prod
```

## Artifact Registry

Create a Docker repository for the Cloud Run image:

```bash
gcloud artifacts repositories create bigquery-readonly-mcp \
  --repository-format=docker \
  --location=asia-northeast1 \
  --description="BigQuery readonly MCP images" \
  --project bigquery-mcp-prod
```

## Secret Manager

Store secret values in Secret Manager. Do not put secret values in GitHub or `env.example.yaml`.

```bash
printf '%s' '<oauth-client-id>' | gcloud secrets create google-oauth-client-id \
  --data-file=- \
  --project bigquery-mcp-prod

printf '%s' '<oauth-client-secret>' | gcloud secrets create google-oauth-client-secret \
  --data-file=- \
  --project bigquery-mcp-prod

openssl rand -base64 32 | gcloud secrets create bigquery-mcp-session-secret \
  --data-file=- \
  --project bigquery-mcp-prod
```

If a secret already exists, add a new version instead:

```bash
printf '%s' '<new-value>' | gcloud secrets versions add google-oauth-client-secret \
  --data-file=- \
  --project bigquery-mcp-prod
```

## OAuth Redirect URI

Create a Google OAuth Web application in `bigquery-mcp-prod`, then register the deployed callback URL:

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

IMAGE="asia-northeast1-docker.pkg.dev/bigquery-mcp-prod/bigquery-readonly-mcp/bigquery-readonly-mcp:manual-$(date +%Y%m%d%H%M%S)"

docker build -t "$IMAGE" .
docker push "$IMAGE"

gcloud run deploy bigquery-readonly-mcp \
  --image "$IMAGE" \
  --region asia-northeast1 \
  --project bigquery-mcp-prod \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "BASE_URL=https://<cloud-run-url>,ALLOWED_DOMAIN=impress.co.jp,DEFAULT_PROJECT_ID=ice-sh,MAXIMUM_BYTES_BILLED=1073741824,MAX_RESULTS=1000,QUERY_TIMEOUT_SECONDS=60" \
  --set-secrets "GOOGLE_OAUTH_CLIENT_ID=google-oauth-client-id:latest,GOOGLE_OAUTH_CLIENT_SECRET=google-oauth-client-secret:latest,SESSION_SECRET=bigquery-mcp-session-secret:latest"
```

After the first deploy, update `BASE_URL` to the actual Cloud Run URL and redeploy if needed. The OAuth redirect URI must match the same URL.

## Health Check

```bash
curl -fsS "https://<cloud-run-url>/healthz"
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
- `https://<cloud-run-url>/healthz` returns `{"status":"ok"}`.
- HTTPS endpoint is registered as OAuth redirect URI.
- Secret values are supplied from Secret Manager.
- Cloud Logging receives app logs from the service.

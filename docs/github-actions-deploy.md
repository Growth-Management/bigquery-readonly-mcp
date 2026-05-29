# GitHub Actions Deployment Setup

This guide covers the Phase 6 setup for deploying `Growth-Management/bigquery-readonly-mcp` to Cloud Run through GitHub Actions.

## Fixed Defaults

- GitHub repository: `Growth-Management/bigquery-readonly-mcp`
- Deploy project: `ice-sh`
- Region: `asia-northeast1`
- Cloud Run service: `bigquery-readonly-mcp`
- Artifact Registry repository: `bigquery-readonly-mcp`
- Initial BigQuery validation project: `ice-sh`

Deployment is managed per GCP project. This guide uses `ice-sh` for the initial deployment. For another project, create a separate deploy service account, WIF binding, Artifact Registry repository, Secret Manager secrets, Cloud Run service, and GitHub Secrets for that project.

## GitHub Secrets

Set these repository secrets in `Growth-Management/bigquery-readonly-mcp`:

| Secret | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `ice-sh` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full Workload Identity Provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy service account email |
| `BASE_URL` | Cloud Run URL or custom domain |

Example provider resource name:

```text
projects/<project-number>/locations/global/workloadIdentityPools/github-actions/providers/github-actions
```

Example deploy service account:

```text
github-actions-bigquery-mcp@ice-sh.iam.gserviceaccount.com
```

## Service Accounts

Use two different identities:

- Deploy service account: used by GitHub Actions to build/push/deploy.
- Runtime service account: used by Cloud Run to read Secret Manager values.

Neither service account should be used to run BigQuery queries on behalf of users. BigQuery queries use the OAuth access token of the logged-in user.

## Create Deploy Service Account

```bash
gcloud iam service-accounts create github-actions-bigquery-mcp \
  --display-name="GitHub Actions BigQuery MCP deploy" \
  --project ice-sh
```

Set a variable for later commands:

```bash
DEPLOY_SA="github-actions-bigquery-mcp@ice-sh.iam.gserviceaccount.com"
```

## Grant Deploy Permissions

Grant only deployment-related permissions:

```bash
gcloud projects add-iam-policy-binding ice-sh \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding ice-sh \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding ice-sh \
  --member="serviceAccount:${DEPLOY_SA}" \
  --role="roles/iam.serviceAccountUser"
```

`roles/iam.serviceAccountUser` is required so the deploy identity can attach the runtime service account to the Cloud Run service when needed.

## Workload Identity Federation

Enable the IAM Credentials API if it is not already enabled:

```bash
gcloud services enable iamcredentials.googleapis.com \
  --project ice-sh
```

Create a pool:

```bash
gcloud iam workload-identity-pools create github-actions \
  --project ice-sh \
  --location="global" \
  --display-name="GitHub Actions"
```

Create a provider restricted to this repository:

```bash
gcloud iam workload-identity-pools providers create-oidc github-actions \
  --project ice-sh \
  --location="global" \
  --workload-identity-pool="github-actions" \
  --display-name="GitHub Actions provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository == 'Growth-Management/bigquery-readonly-mcp'"
```

Allow that repository to impersonate the deploy service account:

```bash
PROJECT_NUMBER="$(gcloud projects describe ice-sh --format='value(projectNumber)')"

gcloud iam service-accounts add-iam-policy-binding "${DEPLOY_SA}" \
  --project ice-sh \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions/attribute.repository/Growth-Management/bigquery-readonly-mcp"
```

Use this as `GCP_WORKLOAD_IDENTITY_PROVIDER`:

```bash
echo "projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions/providers/github-actions"
```

## Runtime Secret Access

The Cloud Run runtime service account needs access to Secret Manager values referenced by the workflow.

If using the default Compute service account as runtime identity, first identify it:

```bash
PROJECT_NUMBER="$(gcloud projects describe ice-sh --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
```

Grant secret access:

```bash
for SECRET in google-oauth-client-id google-oauth-client-secret bigquery-mcp-session-secret; do
  gcloud secrets add-iam-policy-binding "${SECRET}" \
    --project ice-sh \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

For tighter control, create a dedicated runtime service account and update the workflow to pass `--service-account` during `gcloud run deploy`.

## Deploy Check

After setting the secrets, run the workflow manually from GitHub Actions or push to `main`.

Confirm the workflow:

1. Installs Python dependencies.
2. Runs `pytest`.
3. Authenticates to Google Cloud through Workload Identity Federation.
4. Builds and pushes the Docker image to Artifact Registry.
5. Deploys `bigquery-readonly-mcp` to Cloud Run.

Then run:

```bash
scripts/check-healthz.sh "${BASE_URL}"
```

Expected response:

```json
{"status":"ok"}
```

## Phase 6 Done Criteria

- Workload Identity Federation provider exists and is restricted to `Growth-Management/bigquery-readonly-mcp`.
- Deploy service account exists.
- Deploy service account has Artifact Registry and Cloud Run deploy permissions.
- GitHub Secrets are set.
- GitHub Actions deploy workflow completes successfully from `main`.
- Cloud Run `/healthz` succeeds after deploy.

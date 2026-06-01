# GitHub Actions Deployment Setup

This guide covers the Phase 6 setup for testing and deploying `Growth-Management/bigquery-readonly-mcp` to Cloud Run through GitHub Actions.

## Fixed Defaults

- GitHub repository: `Growth-Management/bigquery-readonly-mcp`
- Deploy project: `ice-sh`
- Region: `asia-northeast1`
- Cloud Run service: `bigquery-readonly-mcp`
- Artifact Registry repository: `bigquery-readonly-mcp`
- Initial BigQuery validation project: `ice-sh`

Deployment is managed per GCP project. This guide uses `ice-sh` for the initial deployment. For another project, create a separate deploy service account, WIF binding, Artifact Registry repository, Secret Manager secrets, Cloud Run service, KMS key, Firestore TTL settings, and GitHub Secrets for that project.

## Workflow Triggers

The workflow has two paths:

- `pull_request` to `main`: runs the `test` job only. It installs dependencies and runs `pytest`. It does not authenticate to Google Cloud and does not deploy.
- `push` to `main` or `workflow_dispatch`: runs `test`, then deploys to Cloud Run if tests pass.

This keeps PR validation read-only while still allowing main/manual deployments.

## GitHub Secrets

Set these repository secrets in `Growth-Management/bigquery-readonly-mcp`:

| Secret | Value |
| --- | --- |
| `GCP_PROJECT_ID` | `ice-sh` |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Full Workload Identity Provider resource name |
| `GCP_DEPLOY_SERVICE_ACCOUNT` | Deploy service account email |
| `BASE_URL` | Cloud Run URL or custom domain |

The Cloud Run service also references these Secret Manager secrets during deploy:

| Secret Manager secret | Runtime env var |
| --- | --- |
| `google-oauth-client-id` | `GOOGLE_OAUTH_CLIENT_ID` |
| `google-oauth-client-secret` | `GOOGLE_OAUTH_CLIENT_SECRET` |
| `bigquery-mcp-session-secret` | `SESSION_SECRET` |
| `bigquery-mcp-token-hash-secret` | `TOKEN_HASH_SECRET` |

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
- Runtime service account: used by Cloud Run to read Secret Manager values, read/write Firestore persistence records, and encrypt/decrypt OAuth tokens with KMS.

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
for SECRET in google-oauth-client-id google-oauth-client-secret bigquery-mcp-session-secret bigquery-mcp-token-hash-secret; do
  gcloud secrets add-iam-policy-binding "${SECRET}" \
    --project ice-sh \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

The runtime service account also needs Firestore and KMS access for OAuth persistence:

```bash
gcloud projects add-iam-policy-binding ice-sh \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/datastore.user"

gcloud kms keys add-iam-policy-binding oauth-token-encryption \
  --keyring=bigquery-readonly-mcp \
  --location=asia-northeast1 \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" \
  --project=ice-sh
```

For tighter control, create a dedicated runtime service account and update the workflow to pass `--service-account` during `gcloud run deploy`.

## Cloud Run Runtime Settings

The workflow deploys these OAuth persistence settings to Cloud Run:

- `FIRESTORE_PROJECT_ID=ice-sh`
- `OAUTH_TOKEN_COLLECTION=oauth_token_records`
- `OAUTH_AUTH_REQUEST_COLLECTION=oauth_auth_requests`
- `OAUTH_AUTHORIZATION_CODE_COLLECTION=oauth_authorization_codes`
- `MCP_SESSION_COLLECTION=mcp_sessions`
- `OAUTH_STATE_TTL_SECONDS=600`
- `OAUTH_CODE_TTL_SECONDS=600`
- `SESSION_TTL_SECONDS=3600`
- `KMS_KEY_NAME=projects/ice-sh/locations/asia-northeast1/keyRings/bigquery-readonly-mcp/cryptoKeys/oauth-token-encryption`

`TOKEN_HASH_SECRET` is read from Secret Manager as `bigquery-mcp-token-hash-secret`.

## Deploy Check

After setting the secrets and runtime IAM, run the workflow manually from GitHub Actions or push to `main`.

Confirm the workflow:

1. Installs Python dependencies.
2. Runs `pytest`.
3. Authenticates to Google Cloud through Workload Identity Federation.
4. Builds and pushes the Docker image to Artifact Registry.
5. Deploys `bigquery-readonly-mcp` to Cloud Run with OAuth persistence settings.

Then run:

```bash
scripts/check-healthz.sh "${BASE_URL}"
```

Expected response:

```json
{"status":"ok"}
```

## Phase 6 Done Criteria

- Pull requests to `main` run `pytest` without deploying.
- Workload Identity Federation provider exists and is restricted to `Growth-Management/bigquery-readonly-mcp`.
- Deploy service account exists.
- Deploy service account has Artifact Registry and Cloud Run deploy permissions.
- GitHub Secrets are set.
- Secret Manager secrets are set, including `bigquery-mcp-token-hash-secret`.
- Runtime service account has Secret Manager, Firestore, and KMS permissions.
- GitHub Actions deploy workflow completes successfully from `main` or `workflow_dispatch`.
- Cloud Run `/health` succeeds after deploy.

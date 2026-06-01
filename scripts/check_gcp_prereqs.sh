#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ice-sh}"
REGION="${REGION:-asia-northeast1}"
SERVICE="${SERVICE:-bigquery-readonly-mcp}"
KEYRING="${KEYRING:-bigquery-readonly-mcp}"
KMS_KEY="${KMS_KEY:-oauth-token-encryption}"
BASE_URL="${BASE_URL:-}"

REQUIRED_SECRETS=(
  google-oauth-client-id
  google-oauth-client-secret
  bigquery-mcp-session-secret
  bigquery-mcp-token-hash-secret
)

TTL_COLLECTIONS=(
  oauth_auth_requests:expires_at
  oauth_authorization_codes:expires_at
  mcp_sessions:expires_at
)

ok() { printf 'OK: %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

policy_has_binding() {
  local policy_json="$1"
  local member="$2"
  local role="$3"
  jq -e --arg member "$member" --arg role "$role" '
    .bindings[]? | select(.role == $role) | .members[]? | select(. == $member)
  ' <<<"$policy_json" >/dev/null
}

require_command gcloud
require_command jq

ACTIVE_ACCOUNT="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n 1)"
[[ -n "${ACTIVE_ACCOUNT}" ]] || fail "No active gcloud account. Run gcloud auth login first."
ok "gcloud account ${ACTIVE_ACCOUNT}"

PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')"
[[ -n "${PROJECT_NUMBER}" ]] || fail "Could not resolve project number for ${PROJECT_ID}"
ok "project ${PROJECT_ID} number ${PROJECT_NUMBER}"

SERVICE_ACCOUNT="$(gcloud run services describe "${SERVICE}" \
  --region "${REGION}" \
  --project "${PROJECT_ID}" \
  --format='value(spec.template.spec.serviceAccountName)' 2>/dev/null || true)"

if [[ -z "${SERVICE_ACCOUNT}" ]]; then
  SERVICE_ACCOUNT="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
  warn "Cloud Run service account was not explicit; assuming default compute service account ${SERVICE_ACCOUNT}"
else
  ok "Cloud Run runtime service account ${SERVICE_ACCOUNT}"
fi

RUNTIME_MEMBER="serviceAccount:${SERVICE_ACCOUNT}"

for secret in "${REQUIRED_SECRETS[@]}"; do
  gcloud secrets describe "${secret}" --project "${PROJECT_ID}" >/dev/null
  ok "Secret Manager secret exists: ${secret}"

  SECRET_POLICY="$(gcloud secrets get-iam-policy "${secret}" --project "${PROJECT_ID}" --format=json)"
  if policy_has_binding "${SECRET_POLICY}" "${RUNTIME_MEMBER}" "roles/secretmanager.secretAccessor"; then
    ok "${SERVICE_ACCOUNT} can access secret ${secret}"
  else
    fail "${SERVICE_ACCOUNT} is missing roles/secretmanager.secretAccessor on secret ${secret}"
  fi
done

PROJECT_POLICY="$(gcloud projects get-iam-policy "${PROJECT_ID}" --format=json)"
if policy_has_binding "${PROJECT_POLICY}" "${RUNTIME_MEMBER}" "roles/datastore.user"; then
  ok "${SERVICE_ACCOUNT} has roles/datastore.user on ${PROJECT_ID}"
else
  fail "${SERVICE_ACCOUNT} is missing roles/datastore.user on ${PROJECT_ID}"
fi

gcloud kms keys describe "${KMS_KEY}" \
  --keyring "${KEYRING}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" >/dev/null
ok "KMS key exists: projects/${PROJECT_ID}/locations/${REGION}/keyRings/${KEYRING}/cryptoKeys/${KMS_KEY}"

KMS_POLICY="$(gcloud kms keys get-iam-policy "${KMS_KEY}" \
  --keyring "${KEYRING}" \
  --location "${REGION}" \
  --project "${PROJECT_ID}" \
  --format=json)"
if policy_has_binding "${KMS_POLICY}" "${RUNTIME_MEMBER}" "roles/cloudkms.cryptoKeyEncrypterDecrypter"; then
  ok "${SERVICE_ACCOUNT} can encrypt/decrypt with KMS key ${KMS_KEY}"
else
  fail "${SERVICE_ACCOUNT} is missing roles/cloudkms.cryptoKeyEncrypterDecrypter on KMS key ${KMS_KEY}"
fi

TTL_JSON="$(gcloud firestore fields ttls list --project "${PROJECT_ID}" --format=json 2>/dev/null || printf '[]')"
for ttl in "${TTL_COLLECTIONS[@]}"; do
  collection="${ttl%%:*}"
  field="${ttl##*:}"
  if jq -e --arg collection "${collection}" --arg field "${field}" '
    .[]? | select((.name // "") | contains("/collectionGroups/" + $collection + "/fields/" + $field))
  ' <<<"${TTL_JSON}" >/dev/null; then
    ok "Firestore TTL configured: ${collection}.${field}"
  else
    warn "Firestore TTL not found for ${collection}.${field}. Configure before Phase F revalidation."
  fi
done

if [[ -n "${BASE_URL}" ]]; then
  require_command curl
  HEALTH_RESPONSE="$(curl -fsS "${BASE_URL%/}/health")"
  [[ "${HEALTH_RESPONSE}" == *'"status":"ok"'* || "${HEALTH_RESPONSE}" == *'"status": "ok"'* ]] || fail "/health returned unexpected body: ${HEALTH_RESPONSE}"
  ok "Cloud Run /health succeeded at ${BASE_URL%/}/health"
else
  warn "BASE_URL not set; skipping Cloud Run /health check"
fi

ok "GCP prerequisites check completed"

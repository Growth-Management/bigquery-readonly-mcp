# OAuth Persistence Foundation

This document describes the OAuth persistence implementation track.

## Goals

- Keep BigQuery execution tied to the authenticated Google user.
- Remove the design dependency on Cloud Run instance memory.
- Store long-lived refresh tokens only as KMS-encrypted ciphertext.
- Store OAuth state, authorization codes, and MCP bearer sessions as short-lived Firestore records.
- Refresh expired Google access tokens from the encrypted refresh token without service-account impersonation.
- Emit audit events without logging tokens, authorization codes, client secrets, or plaintext/ciphertext values.

## Implemented Scope

This branch adds the persistence foundation and wires OAuth request state, internal authorization codes, MCP bearer sessions, access-token refresh, and admin token lifecycle operations into Firestore/KMS:

- Generic audit events with recursive secret scrubbing.
- Firestore and Cloud KMS dependencies.
- Persistence-related environment settings.
- HMAC-based identifiers for OAuth state, authorization codes, and MCP bearer sessions.
- KMS token encryption/decryption helper with Additional Authenticated Data.
- Dataclass models for token records, OAuth auth requests, internal authorization codes, and MCP sessions.
- A Firestore store wrapper with one-time consume helpers, token-record partial updates, token-record deletion, and MCP session revocation by token record.
- `/oauth/authorize` writes OAuth request state to `oauth_auth_requests`.
- `/oauth/callback` consumes OAuth request state from Firestore, writes an encrypted token record, and writes an internal authorization code record.
- `/oauth/token` consumes the internal authorization code from Firestore and creates a hashed persistent MCP bearer session in `mcp_sessions`.
- `/mcp` resolves the bearer token through `mcp_sessions`, loads the associated token record, decrypts a still-valid access token, or refreshes an expired access token using the encrypted refresh token.
- Existing encrypted refresh tokens are preserved when Google does not return a new refresh token during a later OAuth callback.
- `invalid_grant`, missing refresh token, and malformed refresh responses transition the token record toward explicit reauthentication instead of falling back to unsafe behavior.
- `scripts/manage_oauth_tokens.py` supports disable, delete, and force reauth actions for persisted user connections.
- Firestore TTL, KMS rotation, and token lifecycle review operating procedures are documented below.

## Firestore Collections

- `oauth_token_records`: long-lived user OAuth token records.
- `oauth_auth_requests`: short-lived OAuth request state records.
- `oauth_authorization_codes`: short-lived internal authorization code records.
- `mcp_sessions`: MCP bearer token session records.

Short-lived collections should use an `expires_at` TTL field, but application code must still check `expires_at` because Firestore TTL deletion is not immediate.

## Token Hashing

Raw secrets are not used as document IDs.

- OAuth auth request ID: HMAC of Google OAuth state.
- OAuth authorization code ID: HMAC of internal authorization code.
- MCP session ID: HMAC of bearer token.
- OAuth token record ID: stable SHA-256 hash of Google subject.

Use `TOKEN_HASH_SECRET` when available. If omitted, the app falls back to `SESSION_SECRET`.

## KMS Encryption

Refresh tokens and short-lived access tokens are encrypted with a Cloud KMS symmetric key. The Additional Authenticated Data format is:

```text
bigquery-readonly-mcp:v1:oauth_token_records:{document_id}:{google_sub}
```

This binds ciphertext to the intended Firestore token record and Google subject. Token records store the KMS key name used for each token ciphertext so future key rotation can be handled without guessing which key encrypted older records.

## Access Token Refresh

`/mcp` resolves a bearer session to a user token record before BigQuery tools run.

- If the stored access token exists and expires more than five minutes in the future, it is decrypted and used for BigQuery.
- If the access token is missing, expired, or within the five-minute refresh window, the encrypted refresh token is decrypted and exchanged at Google's OAuth token endpoint for a new user access token.
- The refreshed access token is encrypted, stored back into Firestore with a new expiry, and then used for the BigQuery call.
- If Google returns a replacement refresh token, it is encrypted and stored, replacing the previous refresh token.
- If the refresh token is missing or Google returns `invalid_grant`, the token record is marked `reauth_required` and the MCP request returns 401 so the user can start `/oauth/authorize` again.

The refresh flow still uses the user's Google OAuth grant. The Cloud Run service account only reads/writes Firestore, decrypts/encrypts tokens with KMS, and accesses service-level secrets.

## Admin Operations

Use `scripts/manage_oauth_tokens.py` for operator-controlled lifecycle actions. Run it from the repository root with the same environment settings used by the service, including Firestore and KMS configuration.

Target a connection by either token record ID or Google subject:

```bash
python scripts/manage_oauth_tokens.py force_reauth \
  --google-sub "GOOGLE_SUB" \
  --reason "periodic consent review" \
  --actor-email "admin@impress.co.jp"
```

```bash
python scripts/manage_oauth_tokens.py disable \
  --token-record-id "TOKEN_RECORD_ID" \
  --reason "user no longer requires access" \
  --actor-email "admin@impress.co.jp"
```

```bash
python scripts/manage_oauth_tokens.py delete \
  --token-record-id "TOKEN_RECORD_ID" \
  --reason "user deletion request" \
  --actor-email "admin@impress.co.jp"
```

Actions:

- `force_reauth`: marks the token record `reauth_required` and revokes related MCP sessions. The next MCP request receives 401 and the user must reauthorize.
- `disable`: marks the token record `disabled` and revokes related MCP sessions. This is appropriate when access should be stopped but an audit trail should remain.
- `delete`: marks the token record `deleted`, revokes related MCP sessions, then deletes the token record. Use this only when removing the stored user connection is intended.

Each admin action emits an `oauth_token_admin_action` audit event. The event includes the actor email, target user email, action, token record ID, and number of revoked sessions, but never token ciphertext or plaintext.

## Firestore TTL Operations

Configure TTL for records that are intentionally short-lived. TTL is cleanup only; authorization correctness must come from application checks for `expires_at`, `consumed_at`, and `status`.

Recommended TTL fields:

- `oauth_auth_requests.expires_at`: deletes expired OAuth request state.
- `oauth_authorization_codes.expires_at`: deletes expired internal authorization codes.
- `mcp_sessions.expires_at`: deletes expired MCP bearer sessions.
- `oauth_token_records.expire_at`: optional only for records intentionally scheduled for deletion after disable/delete retention review.

Initial setup for `ice-sh`:

```bash
gcloud firestore fields ttls update expires_at \
  --collection-group=oauth_auth_requests \
  --project=ice-sh \
  --enable-ttl

gcloud firestore fields ttls update expires_at \
  --collection-group=oauth_authorization_codes \
  --project=ice-sh \
  --enable-ttl

gcloud firestore fields ttls update expires_at \
  --collection-group=mcp_sessions \
  --project=ice-sh \
  --enable-ttl
```

Optional deletion scheduling for token records:

```bash
gcloud firestore fields ttls update expire_at \
  --collection-group=oauth_token_records \
  --project=ice-sh \
  --enable-ttl
```

Verification:

```bash
gcloud firestore fields ttls list --project=ice-sh
```

Operational notes:

- Firestore TTL deletion is asynchronous and may lag. Never rely on TTL alone to reject expired OAuth state, authorization codes, or MCP sessions.
- Short-lived records must remain rejected by code immediately after `expires_at` even before TTL deletes them.
- Review TTL configuration after collection names change or when deploying a separate project.
- Add a Cloud Logging alert if expired `oauth_auth_requests`, `oauth_authorization_codes`, or `mcp_sessions` grow unexpectedly, because that can indicate TTL was not enabled or is delayed.

## KMS Rotation Operations

Use Cloud KMS key versions for rotation. The application stores the KMS key name used for each token ciphertext, so old ciphertext can remain decryptable while new writes use the primary key version behind the same crypto key.

Recommended setup:

```bash
gcloud kms keyrings create bigquery-readonly-mcp \
  --location=asia-northeast1 \
  --project=ice-sh

gcloud kms keys create oauth-token-encryption \
  --keyring=bigquery-readonly-mcp \
  --location=asia-northeast1 \
  --purpose=encryption \
  --rotation-period=90d \
  --next-rotation-time="2026-09-01T00:00:00Z" \
  --project=ice-sh
```

Grant the Cloud Run runtime service account only the key-level permission it needs:

```bash
gcloud kms keys add-iam-policy-binding oauth-token-encryption \
  --keyring=bigquery-readonly-mcp \
  --location=asia-northeast1 \
  --member="serviceAccount:RUNTIME_SERVICE_ACCOUNT" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter" \
  --project=ice-sh
```

Routine rotation check:

```bash
gcloud kms keys versions list \
  --key=oauth-token-encryption \
  --keyring=bigquery-readonly-mcp \
  --location=asia-northeast1 \
  --project=ice-sh
```

Operational notes:

- Do not disable or destroy old key versions while Firestore may still contain ciphertext encrypted by those versions.
- Before disabling any old key version, confirm active token records no longer depend on it or run a controlled reauthorization cycle for affected users.
- If key compromise is suspected, first disable affected OAuth connections with `scripts/manage_oauth_tokens.py disable`, then rotate KMS and force reauthorization. Do not try to keep suspect refresh tokens alive.
- KMS rotation does not change BigQuery execution identity. It only protects stored OAuth token material.

## Token Lifecycle Review

Run a lightweight monthly review, and run an immediate review after personnel changes, incident response, or OAuth consent changes.

Review checklist:

- Confirm every active token record belongs to an expected `impress.co.jp` user.
- Confirm `status` distribution: `active`, `reauth_required`, `disabled`, and any deletion-scheduled records.
- Confirm stale `mcp_sessions` are being rejected by code and cleaned by TTL.
- Confirm `last_refresh_at` and `last_used_at` patterns match expected use. Long-unused active records should be disabled or forced through reauth.
- Confirm `last_error_class` and `reauth_required_reason` are reviewed and cleared only by successful reauthorization.
- Confirm admin actions have matching `oauth_token_admin_action` audit events.
- Confirm no logs contain token plaintext, ciphertext, authorization code, MCP bearer token, or client secret values.

Suggested action thresholds:

- No use for 30 days: `force_reauth` or `disable`, depending on business need.
- User removed from the allowed organization or team: `disable` immediately.
- User deletion request: `delete` after confirming audit and retention expectations.
- Repeated `invalid_grant`: leave `reauth_required` and ask the user to start `/oauth/authorize` again.
- Scope or consent change: `force_reauth` for affected users.

Cloud Logging filters:

```text
jsonPayload.event_type="oauth_token_admin_action"
```

```text
jsonPayload.event_type="mcp_session_rejected"
jsonPayload.error_class="token_record_unavailable"
```

```text
jsonPayload.event_type="bigquery_mcp_tool_call"
jsonPayload.success=false
```

Keep lifecycle reviews focused on least privilege and auditability: user access should be explainable from OAuth status, BigQuery IAM, MCP session state, and Cloud Logging events.

## Required Environment Variables

New variables:

- `TOKEN_HASH_SECRET`
- `FIRESTORE_PROJECT_ID`
- `OAUTH_TOKEN_COLLECTION`
- `OAUTH_AUTH_REQUEST_COLLECTION`
- `OAUTH_AUTHORIZATION_CODE_COLLECTION`
- `MCP_SESSION_COLLECTION`
- `OAUTH_STATE_TTL_SECONDS`
- `OAUTH_CODE_TTL_SECONDS`
- `KMS_KEY_NAME`

Existing variables remain required.

## IAM

The Cloud Run runtime service account needs:

- Firestore read/write for the persistence collections. Initial implementation may use `roles/datastore.user`; tighten with a custom role before broader rollout.
- `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the specific OAuth token KMS key.
- `roles/secretmanager.secretAccessor` only for service-level secrets such as OAuth client secret and session/hash secrets.

The deploy service account remains separate from the runtime service account. BigQuery query execution still uses the logged-in user's OAuth token, not the Cloud Run service account.

## Audit Logging

Use `audit_event()` for OAuth, token lifecycle, MCP session, and admin events. Use the existing `audit_log()` wrapper for BigQuery tool calls.

The audit scrubber redacts fields with dangerous names such as:

- `access_token`
- `refresh_token`
- `authorization_code`
- `code`
- `code_verifier`
- `client_secret`
- `bearer_token`
- `session_id`
- `mcp_session`
- `ciphertext`
- `plaintext`

Do not log SQL result rows or token values.

## Remaining Implementation Steps

1. Add broader reauth-required handling for scope mismatch and consent changes.
2. Validate TTL, KMS rotation, and lifecycle review procedures during Phase F `ice-sh` verification.

# OAuth Persistence Foundation

This document describes the first implementation slice for the OAuth persistence improvement track.

## Goals

- Keep BigQuery execution tied to the authenticated Google user.
- Remove the design dependency on Cloud Run instance memory.
- Store long-lived refresh tokens only as KMS-encrypted ciphertext.
- Store OAuth state, authorization codes, and MCP bearer sessions as short-lived Firestore records.
- Emit audit events without logging tokens, authorization codes, client secrets, or plaintext/ciphertext values.

## Implemented Scope

This branch adds the foundation and wires OAuth request state, internal authorization codes, and MCP bearer sessions into Firestore:

- Generic audit events with recursive secret scrubbing.
- Firestore and Cloud KMS dependencies.
- Persistence-related environment settings.
- HMAC-based identifiers for OAuth state, authorization codes, and MCP bearer sessions.
- KMS token encryption/decryption helper with Additional Authenticated Data.
- Dataclass models for token records, OAuth auth requests, internal authorization codes, and MCP sessions.
- A Firestore store wrapper with one-time consume helpers.
- `/oauth/authorize` writes OAuth request state to `oauth_auth_requests`.
- `/oauth/callback` consumes OAuth request state from Firestore, writes an encrypted token record, and writes an internal authorization code record.
- `/oauth/token` consumes the internal authorization code from Firestore and creates a hashed persistent MCP bearer session in `mcp_sessions`.
- `/mcp` resolves the bearer token through `mcp_sessions`, loads the associated token record, and decrypts the stored access token for BigQuery tool execution.
- Existing encrypted refresh tokens are preserved when Google does not return a new refresh token during a later OAuth callback.

Access-token refresh from the encrypted refresh token is still a remaining implementation step. Until then, the stored access token is used until it expires.

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

Refresh tokens and the short-lived access token are encrypted with a Cloud KMS symmetric key. The Additional Authenticated Data format is:

```text
bigquery-readonly-mcp:v1:oauth_token_records:{document_id}:{google_sub}
```

This binds ciphertext to the intended Firestore token record and Google subject.

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

1. Add refresh-token based access token refresh handling.
2. Add reauth-required state transitions for `invalid_grant`, scope mismatch, and missing refresh token.
3. Add admin scripts for disable, delete, and force reauth.

# All-Project IAM User Pilot

This document records the approved pilot change from a single allowed BigQuery project to user-IAM-scoped project access.

## Status

Approved for the current pilot user as of 2026-06-09.

Security owner decision:

> The approved user may use the MCP for any BigQuery project that the user can read through their own Google account IAM.

Validated on 2026-06-09 with `sinohara@impress.co.jp`.

## Current Scope

| Field | Value |
| --- | --- |
| Cloud Run deployment project | `ice-sh` |
| Default project | `ice-mp` |
| Application project allowlist | empty, `ALLOWED_PROJECT_IDS=` |
| Application dataset allowlist | empty, `ALLOWED_DATASET_IDS=` |
| Application user allowlist | `sinohara@impress.co.jp` |
| Session backend | `firestore` |
| Session TTL | `3600` seconds |

## Effective Access Model

BigQuery execution still uses the logged-in user's Google OAuth token.

The MCP does not grant BigQuery access. With `ALLOWED_PROJECT_IDS=` empty, project visibility and query authorization are governed by the user's own BigQuery IAM, including:

- Direct project IAM bindings.
- Dataset-level access entries.
- Google Group membership.
- Folder or organization inheritance.
- Authorized views or linked datasets, when applicable.

The application still restricts users with `ALLOWED_USER_EMAILS=sinohara@impress.co.jp`, so this pilot is not open to every `impress.co.jp` user.

## Why This Is Acceptable For The Pilot

- The pilot remains single-user: `sinohara@impress.co.jp` only.
- The security owner explicitly approved user-IAM-scoped project access.
- BigQuery IAM remains the source of truth for readable projects and datasets.
- SQL guard still allows only readonly `SELECT` / `WITH` queries.
- Cloud Logging continues to record `user_email`, `tool`, `project_id`, `success`, `error`, and `rejection_reason`.
- `DEFAULT_PROJECT_ID=ice-mp` keeps ordinary use oriented to the pilot project while still allowing explicit `project_id` values when the user has IAM.

## Risks And Controls

| Risk | Control |
| --- | --- |
| User can see more projects than expected through inherited IAM or groups | Review IAM / groups when access looks broader than expected. MCP follows BigQuery IAM. |
| Accidental project selection | `DEFAULT_PROJECT_ID=ice-mp`, audit logs include `project_id`, and validation should include explicit project checks. |
| Additional users would inherit this broader project behavior | Keep `ALLOWED_USER_EMAILS=sinohara@impress.co.jp` until user expansion is separately approved. |
| Dataset exposure is too broad inside a project | Keep BigQuery dataset IAM tight; optionally configure `ALLOWED_DATASET_IDS` later. |

## Deployment Change

GitHub Actions deploy default is updated to:

```text
ALLOWED_PROJECT_IDS=
ALLOWED_DATASET_IDS=
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
```

This means future deploys preserve the approved all-project-by-user-IAM behavior.

## Validation Results

Validated on 2026-06-09 from Cloud Shell with `sinohara@impress.co.jp`.

### Cloud Run Environment

Cloud Run service environment:

```text
DEFAULT_PROJECT_ID=ice-mp
ALLOWED_PROJECT_IDS=
ALLOWED_DATASET_IDS=
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
SESSION_STORE_BACKEND=firestore
SESSION_TTL_SECONDS=3600
```

Cloud Shell `jq` displayed empty env values as `null`; this is acceptable and represents an empty allowlist value in this context.

### MCP Tool Calls

`list_projects` returned multiple IAM-visible projects, not only `ice-mp`. Example project IDs returned:

```text
sysmgmt-cloudrun-bridge
bq-mcp-access-denied-test-2
bq-mcp-access-denied-test
ice-ec-project
jumpplus-acs-v2
ice-magapocke-project
ice-shinchan-project
ice-mp
ice-qb
ice-sh
jumpplus-dev
ice-gm-202012
mangaplus-f14c0
jumpplus-4a5f4
magazinepocket-961
```

`list_datasets(project_id="ice-sh")` succeeded and returned `ice-sh` datasets. This confirms `ice-sh` is no longer blocked by `ALLOWED_PROJECT_IDS`.

### Audit Logs

Cloud Logging showed the post-change success records:

```text
2026-06-09T03:06:19.337133Z list_projects project_id=ice-mp success=true rejection_reason=null
2026-06-09T03:07:15.614857Z list_datasets project_id=ice-sh success=true rejection_reason=null
```

Older logs from 2026-06-08 still show `project_not_allowed` for `ice-sh`; those records predate this change and are expected historical evidence of the previous narrow pilot boundary.

## Validation Plan For Future Changes

After deployment, validate with the approved user:

1. Confirm Cloud Run env shows `ALLOWED_PROJECT_IDS=` and `ALLOWED_USER_EMAILS=<approved user>`.
2. Run `list_projects` and confirm it returns the user's IAM-visible projects.
3. Run `list_datasets` for `ice-mp` and one other known authorized project.
4. Run a small `dry_run_query` on an authorized project.
5. Confirm a project without BigQuery IAM returns a BigQuery permission error, not a project allowlist rejection.
6. Confirm Cloud Logging records the actual `project_id` and `user_email`.

## Rollback

To return to the previous narrow pilot boundary:

```text
ALLOWED_PROJECT_IDS=ice-mp
ALLOWED_DATASET_IDS=
ALLOWED_USER_EMAILS=sinohara@impress.co.jp
```

Then redeploy Cloud Run and confirm cross-project calls are rejected with `rejection_reason="project_not_allowed"`.

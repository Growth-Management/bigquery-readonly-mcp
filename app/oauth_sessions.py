from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
import secrets
import time

import httpx

from app.config import Settings
from app.firestore_store import FirestoreStore
from app.persistence_models import McpSessionRecord, expires_in, utc_now
from app.security import mcp_session_id, token_aad
from app.sessions import UserSession
from app.token_crypto import KmsTokenCipher

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
ACCESS_TOKEN_REFRESH_SKEW_SECONDS = 300


class PersistentSessionError(ValueError):
    pass


class GoogleTokenRefreshError(PersistentSessionError):
    pass


def create_persistent_mcp_session(
    *,
    store: FirestoreStore,
    settings: Settings,
    user_token_record_id: str,
    user_email: str,
    google_sub: str,
    scopes: list[str],
) -> dict[str, object]:
    bearer_token = secrets.token_urlsafe(32)
    session_hash = mcp_session_id(bearer_token, settings.effective_token_hash_secret)
    store.save_mcp_session(
        session_hash,
        McpSessionRecord(
            session_hash=session_hash,
            user_token_record_id=user_token_record_id,
            user_email=user_email,
            google_sub=google_sub,
            expires_at=expires_in(settings.session_ttl_seconds),
        ),
    )
    return {
        "access_token": bearer_token,
        "token_type": "Bearer",
        "expires_in": settings.session_ttl_seconds,
        "scope": " ".join(scopes),
    }


def _to_utc_datetime(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _access_token_needs_refresh(token_record: dict[str, Any], now: datetime | None = None) -> bool:
    if not token_record.get("access_token_ciphertext"):
        return True
    expires_at = _to_utc_datetime(token_record.get("access_token_expires_at"))
    if expires_at is None:
        return True
    return expires_at <= (now or utc_now()) + timedelta(seconds=ACCESS_TOKEN_REFRESH_SKEW_SECONDS)


def _mark_reauth_required(store: FirestoreStore, token_record_id: str, *, reason: str, error_class: str | None = None) -> None:
    store.update_token_record(
        token_record_id,
        {
            "status": "reauth_required",
            "reauth_required_reason": reason,
            "last_error_class": error_class or reason,
        },
    )


def _token_kms_key_name(token_record: dict[str, Any], key_name: str, settings: Settings) -> str | None:
    return token_record.get(key_name) or token_record.get("refresh_token_kms_key_name") or settings.kms_key_name


def _refresh_google_access_token(
    *,
    token_record_id: str,
    token_record: dict[str, Any],
    store: FirestoreStore,
    settings: Settings,
    cipher: KmsTokenCipher,
    aad: bytes,
    http_client: Any = httpx,
) -> str:
    refresh_token_ciphertext = token_record.get("refresh_token_ciphertext")
    if not refresh_token_ciphertext:
        _mark_reauth_required(store, token_record_id, reason="missing_refresh_token")
        raise GoogleTokenRefreshError("OAuth token record is missing a refresh token")

    refresh_token = cipher.decrypt_ciphertext(
        refresh_token_ciphertext,
        kms_key_name=_token_kms_key_name(token_record, "refresh_token_kms_key_name", settings),
        aad=aad,
    )

    try:
        response = http_client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            timeout=20,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        error_class = "google_token_refresh_http_error"
        reason = error_class
        try:
            body = exc.response.json()
            reason = str(body.get("error") or error_class)
        except ValueError:
            pass
        if reason == "invalid_grant":
            _mark_reauth_required(store, token_record_id, reason=reason, error_class=error_class)
        else:
            store.update_token_record(token_record_id, {"last_error_class": error_class})
        raise GoogleTokenRefreshError("Google OAuth access token refresh failed") from exc
    except httpx.HTTPError as exc:
        store.update_token_record(token_record_id, {"last_error_class": "google_token_refresh_transport_error"})
        raise GoogleTokenRefreshError("Google OAuth access token refresh failed") from exc

    token_data = response.json()
    access_token = token_data.get("access_token")
    if not access_token:
        _mark_reauth_required(store, token_record_id, reason="refresh_response_missing_access_token")
        raise GoogleTokenRefreshError("Google OAuth refresh response did not include an access token")

    encrypted_access_token = cipher.encrypt(str(access_token), aad=aad)
    expires_at = expires_in(int(token_data.get("expires_in") or 3600))
    updates: dict[str, Any] = {
        "status": "active",
        "access_token_ciphertext": encrypted_access_token.ciphertext,
        "access_token_kms_key_name": encrypted_access_token.kms_key_name,
        "access_token_expires_at": expires_at,
        "last_refresh_at": utc_now(),
        "last_error_class": None,
        "reauth_required_reason": None,
    }
    if token_data.get("scope"):
        updates["scopes"] = str(token_data["scope"]).split()
    if token_data.get("refresh_token"):
        encrypted_refresh_token = cipher.encrypt(str(token_data["refresh_token"]), aad=aad)
        updates["refresh_token_ciphertext"] = encrypted_refresh_token.ciphertext
        updates["refresh_token_kms_key_name"] = encrypted_refresh_token.kms_key_name
    store.update_token_record(token_record_id, updates)
    return str(access_token)


def _resolve_google_access_token(
    *,
    token_record_id: str,
    token_record: dict[str, Any],
    store: FirestoreStore,
    settings: Settings,
    cipher: KmsTokenCipher,
    aad: bytes,
    http_client: Any = httpx,
) -> str:
    if _access_token_needs_refresh(token_record):
        return _refresh_google_access_token(
            token_record_id=token_record_id,
            token_record=token_record,
            store=store,
            settings=settings,
            cipher=cipher,
            aad=aad,
            http_client=http_client,
        )
    return cipher.decrypt_ciphertext(
        token_record["access_token_ciphertext"],
        kms_key_name=_token_kms_key_name(token_record, "access_token_kms_key_name", settings),
        aad=aad,
    )


def resolve_persistent_user_session(
    *,
    bearer_token: str | None,
    store: FirestoreStore,
    settings: Settings,
    cipher: KmsTokenCipher,
    http_client: Any = httpx,
) -> UserSession | None:
    if not bearer_token:
        return None
    session_hash = mcp_session_id(bearer_token, settings.effective_token_hash_secret)
    mcp_session = store.get_mcp_session(session_hash)
    if not mcp_session:
        return None

    token_record_id = str(mcp_session["user_token_record_id"])
    token_record = store.get_token_record(token_record_id)
    if not token_record or token_record.get("status") != "active":
        raise PersistentSessionError("OAuth token record is not active")

    google_sub = str(token_record["google_sub"])
    aad = token_aad(document_id=token_record_id, google_sub=google_sub)
    access_token = _resolve_google_access_token(
        token_record_id=token_record_id,
        token_record=token_record,
        store=store,
        settings=settings,
        cipher=cipher,
        aad=aad,
        http_client=http_client,
    )
    return UserSession(
        email=str(token_record["user_email"]),
        access_token=access_token,
        expires_at=time.time() + settings.query_timeout_seconds,
    )

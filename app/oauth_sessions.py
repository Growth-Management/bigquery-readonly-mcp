import secrets

from app.config import Settings
from app.firestore_store import FirestoreStore
from app.persistence_models import McpSessionRecord, expires_in
from app.security import mcp_session_id, token_aad
from app.sessions import UserSession
from app.token_crypto import KmsTokenCipher


class PersistentSessionError(ValueError):
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


def resolve_persistent_user_session(
    *,
    bearer_token: str | None,
    store: FirestoreStore,
    settings: Settings,
    cipher: KmsTokenCipher,
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
    access_token_ciphertext = token_record.get("access_token_ciphertext")
    if not access_token_ciphertext:
        raise PersistentSessionError("OAuth token record is missing an access token")

    google_sub = str(token_record["google_sub"])
    aad = token_aad(document_id=token_record_id, google_sub=google_sub)
    access_token = cipher.decrypt_ciphertext(
        access_token_ciphertext,
        kms_key_name=token_record.get("refresh_token_kms_key_name") or settings.kms_key_name,
        aad=aad,
    )
    return UserSession(
        email=str(token_record["user_email"]),
        access_token=access_token,
        expires_at=0,
    )

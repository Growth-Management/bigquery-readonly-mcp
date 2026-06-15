import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_ACCESS_TOKEN_TTL_SECONDS = 3600

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserSession:
    email: str
    access_token: str
    expires_at: float


class SessionStore(Protocol):
    def create(
        self,
        *,
        email: str,
        access_token: str,
        ttl_seconds: int,
        refresh_token: str | None = None,
        access_token_expires_in: int | None = None,
    ) -> str:
        ...

    def get(self, session_id: str | None) -> UserSession | None:
        ...

    def prune(self) -> None:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}

    def create(
        self,
        *,
        email: str,
        access_token: str,
        ttl_seconds: int,
        refresh_token: str | None = None,
        access_token_expires_in: int | None = None,
    ) -> str:
        self.prune()
        session_id = secrets.token_urlsafe(32)
        self._sessions[session_id] = UserSession(
            email=email,
            access_token=access_token,
            expires_at=time.time() + ttl_seconds,
        )
        return session_id

    def get(self, session_id: str | None) -> UserSession | None:
        if not session_id:
            return None
        session = self._sessions.get(session_id)
        if not session:
            return None
        if session.expires_at <= time.time():
            self._sessions.pop(session_id, None)
            return None
        return session

    def prune(self) -> None:
        now = time.time()
        expired = [key for key, session in self._sessions.items() if session.expires_at <= now]
        for key in expired:
            self._sessions.pop(key, None)


class EncryptedTokenCodec:
    def __init__(self, session_secret: str) -> None:
        self._aesgcm = AESGCM(hashlib.sha256(session_secret.encode()).digest())

    def encrypt(self, *, session_id: str, access_token: str) -> dict[str, str]:
        encrypted = self.encrypt_value(session_id=session_id, purpose="access_token", value=access_token, legacy_aad=True)
        return {
            "nonce": encrypted["nonce"],
            "access_token_ciphertext": encrypted["ciphertext"],
        }

    def decrypt(self, *, session_id: str, nonce: str, access_token_ciphertext: str) -> str:
        return self.decrypt_value(
            session_id=session_id,
            purpose="access_token",
            nonce=nonce,
            ciphertext=access_token_ciphertext,
            legacy_aad=True,
        )

    def encrypt_value(self, *, session_id: str, purpose: str, value: str, legacy_aad: bool = False) -> dict[str, str]:
        nonce = secrets.token_bytes(12)
        aad = session_id.encode() if legacy_aad else f"{session_id}:{purpose}".encode()
        ciphertext = self._aesgcm.encrypt(nonce, value.encode(), aad)
        return {
            "nonce": base64.urlsafe_b64encode(nonce).decode(),
            "ciphertext": base64.urlsafe_b64encode(ciphertext).decode(),
        }

    def decrypt_value(
        self,
        *,
        session_id: str,
        purpose: str,
        nonce: str,
        ciphertext: str,
        legacy_aad: bool = False,
    ) -> str:
        nonce_bytes = base64.urlsafe_b64decode(nonce.encode())
        ciphertext_bytes = base64.urlsafe_b64decode(ciphertext.encode())
        aad = session_id.encode() if legacy_aad else f"{session_id}:{purpose}".encode()
        plaintext = self._aesgcm.decrypt(nonce_bytes, ciphertext_bytes, aad)
        return plaintext.decode()


class FirestoreSessionStore:
    def __init__(
        self,
        *,
        collection_name: str,
        session_secret: str,
        oauth_client_id: str,
        oauth_client_secret: str,
        refresh_window_seconds: int,
    ) -> None:
        from google.cloud import firestore

        self._client = firestore.Client()
        self._collection = self._client.collection(collection_name)
        self._codec = EncryptedTokenCodec(session_secret)
        self._oauth_client_id = oauth_client_id
        self._oauth_client_secret = oauth_client_secret
        self._refresh_window_seconds = refresh_window_seconds

    def create(
        self,
        *,
        email: str,
        access_token: str,
        ttl_seconds: int,
        refresh_token: str | None = None,
        access_token_expires_in: int | None = None,
    ) -> str:
        self.prune()
        now = time.time()
        session_id = secrets.token_urlsafe(32)
        encrypted_access_token = self._codec.encrypt(session_id=session_id, access_token=access_token)
        data: dict[str, object] = {
            "email": email,
            "expires_at": now + ttl_seconds,
            "access_token_expires_at": now + (access_token_expires_in or DEFAULT_ACCESS_TOKEN_TTL_SECONDS),
            **encrypted_access_token,
        }
        if refresh_token:
            encrypted_refresh_token = self._codec.encrypt_value(
                session_id=session_id,
                purpose="refresh_token",
                value=refresh_token,
            )
            data.update(
                {
                    "refresh_token_nonce": encrypted_refresh_token["nonce"],
                    "refresh_token_ciphertext": encrypted_refresh_token["ciphertext"],
                }
            )
        self._collection.document(session_id).set(data)
        return session_id

    def get(self, session_id: str | None) -> UserSession | None:
        if not session_id:
            return None
        document = self._collection.document(session_id)
        snapshot = document.get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        expires_at = float(data.get("expires_at") or 0)
        now = time.time()
        if expires_at <= now:
            document.delete()
            return None
        try:
            access_token = self._codec.decrypt(
                session_id=session_id,
                nonce=str(data["nonce"]),
                access_token_ciphertext=str(data["access_token_ciphertext"]),
            )
            email = str(data["email"])
            access_token_expires_at = float(data.get("access_token_expires_at") or 0)
        except (KeyError, ValueError, InvalidTag):
            document.delete()
            return None

        if access_token_expires_at and access_token_expires_at <= now + self._refresh_window_seconds:
            refreshed = self._refresh_access_token(document, session_id, data)
            if refreshed is not None:
                access_token = refreshed
            elif access_token_expires_at <= now:
                document.delete()
                return None

        return UserSession(
            email=email,
            access_token=access_token,
            expires_at=expires_at,
        )

    def prune(self) -> None:
        for snapshot in self._collection.where("expires_at", "<=", time.time()).limit(100).stream():
            snapshot.reference.delete()

    def _refresh_access_token(self, document: object, session_id: str, data: dict[str, object]) -> str | None:
        try:
            refresh_token = self._codec.decrypt_value(
                session_id=session_id,
                purpose="refresh_token",
                nonce=str(data["refresh_token_nonce"]),
                ciphertext=str(data["refresh_token_ciphertext"]),
            )
        except (KeyError, ValueError, InvalidTag):
            return None

        try:
            with httpx.Client(timeout=20) as client:
                response = client.post(
                    GOOGLE_TOKEN_URL,
                    data={
                        "client_id": self._oauth_client_id,
                        "client_secret": self._oauth_client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            if response.status_code >= 400:
                logger.warning("refresh_token_exchange_failed", extra={"status_code": response.status_code})
                return None
            token_data = response.json()
            access_token = str(token_data["access_token"])
            expires_in = int(token_data.get("expires_in") or DEFAULT_ACCESS_TOKEN_TTL_SECONDS)
        except (httpx.HTTPError, KeyError, ValueError):
            logger.exception("refresh_token_exchange_error")
            return None

        encrypted_access_token = self._codec.encrypt(session_id=session_id, access_token=access_token)
        update_data: dict[str, object] = {
            **encrypted_access_token,
            "access_token_expires_at": time.time() + expires_in,
        }
        replacement_refresh_token = token_data.get("refresh_token")
        if replacement_refresh_token:
            encrypted_refresh_token = self._codec.encrypt_value(
                session_id=session_id,
                purpose="refresh_token",
                value=str(replacement_refresh_token),
            )
            update_data.update(
                {
                    "refresh_token_nonce": encrypted_refresh_token["nonce"],
                    "refresh_token_ciphertext": encrypted_refresh_token["ciphertext"],
                }
            )
        document.update(update_data)
        return access_token


@lru_cache
def get_session_store(
    backend: str,
    collection_name: str,
    session_secret: str,
    oauth_client_id: str,
    oauth_client_secret: str,
    refresh_window_seconds: int,
) -> SessionStore:
    normalized_backend = backend.lower().strip()
    if normalized_backend == "memory":
        return InMemorySessionStore()
    if normalized_backend == "firestore":
        return FirestoreSessionStore(
            collection_name=collection_name,
            session_secret=session_secret,
            oauth_client_id=oauth_client_id,
            oauth_client_secret=oauth_client_secret,
            refresh_window_seconds=refresh_window_seconds,
        )
    raise ValueError(f"Unsupported SESSION_STORE_BACKEND: {backend}")


def session_store_from_settings(settings: Settings) -> SessionStore:
    return get_session_store(
        settings.session_store_backend,
        settings.firestore_session_collection,
        settings.session_secret,
        settings.oauth_client_id,
        settings.oauth_client_secret,
        settings.oauth_refresh_window_seconds,
    )

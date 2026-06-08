import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings


@dataclass(frozen=True)
class UserSession:
    email: str
    access_token: str
    expires_at: float


class SessionStore(Protocol):
    def create(self, *, email: str, access_token: str, ttl_seconds: int) -> str:
        ...

    def get(self, session_id: str | None) -> UserSession | None:
        ...

    def prune(self) -> None:
        ...


class InMemorySessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}

    def create(self, *, email: str, access_token: str, ttl_seconds: int) -> str:
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
        nonce = secrets.token_bytes(12)
        ciphertext = self._aesgcm.encrypt(nonce, access_token.encode(), session_id.encode())
        return {
            "nonce": base64.urlsafe_b64encode(nonce).decode(),
            "access_token_ciphertext": base64.urlsafe_b64encode(ciphertext).decode(),
        }

    def decrypt(self, *, session_id: str, nonce: str, access_token_ciphertext: str) -> str:
        nonce_bytes = base64.urlsafe_b64decode(nonce.encode())
        ciphertext = base64.urlsafe_b64decode(access_token_ciphertext.encode())
        plaintext = self._aesgcm.decrypt(nonce_bytes, ciphertext, session_id.encode())
        return plaintext.decode()


class FirestoreSessionStore:
    def __init__(self, *, collection_name: str, session_secret: str) -> None:
        from google.cloud import firestore

        self._client = firestore.Client()
        self._collection = self._client.collection(collection_name)
        self._codec = EncryptedTokenCodec(session_secret)

    def create(self, *, email: str, access_token: str, ttl_seconds: int) -> str:
        self.prune()
        session_id = secrets.token_urlsafe(32)
        encrypted = self._codec.encrypt(session_id=session_id, access_token=access_token)
        self._collection.document(session_id).set(
            {
                "email": email,
                "expires_at": time.time() + ttl_seconds,
                **encrypted,
            }
        )
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
        if expires_at <= time.time():
            document.delete()
            return None
        try:
            access_token = self._codec.decrypt(
                session_id=session_id,
                nonce=str(data["nonce"]),
                access_token_ciphertext=str(data["access_token_ciphertext"]),
            )
            email = str(data["email"])
        except (KeyError, ValueError, InvalidTag):
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


@lru_cache
def get_session_store(backend: str, collection_name: str, session_secret: str) -> SessionStore:
    normalized_backend = backend.lower().strip()
    if normalized_backend == "memory":
        return InMemorySessionStore()
    if normalized_backend == "firestore":
        return FirestoreSessionStore(collection_name=collection_name, session_secret=session_secret)
    raise ValueError(f"Unsupported SESSION_STORE_BACKEND: {backend}")


def session_store_from_settings(settings: Settings) -> SessionStore:
    return get_session_store(
        settings.session_store_backend,
        settings.firestore_session_collection,
        settings.session_secret,
    )

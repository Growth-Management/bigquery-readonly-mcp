import secrets
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class UserSession:
    email: str
    access_token: str
    expires_at: float


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


session_store = InMemorySessionStore()

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

TokenStatus = Literal["active", "reauth_required", "disabled", "deleted"]
SessionStatus = Literal["active", "revoked", "expired"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def expires_in(seconds: int) -> datetime:
    return utc_now() + timedelta(seconds=seconds)


@dataclass(frozen=True)
class OAuthAuthRequestRecord:
    google_state_hash: str
    client_redirect_uri: str | None
    client_state: str | None
    code_challenge: str | None
    code_challenge_method: str | None
    requested_scopes: list[str]
    force_consent: bool
    expires_at: datetime
    source: str = "chatgpt_mcp"
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    consumed_at: datetime | None = None

    def to_firestore(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class OAuthAuthorizationCodeRecord:
    auth_code_hash: str
    user_token_record_id: str
    user_email: str
    google_sub: str
    code_challenge: str | None
    code_challenge_method: str | None
    scopes: list[str]
    expires_at: datetime
    client_redirect_uri: str
    client_state: str | None
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    consumed_at: datetime | None = None

    def to_firestore(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class McpSessionRecord:
    session_hash: str
    user_token_record_id: str
    user_email: str
    google_sub: str
    expires_at: datetime
    status: SessionStatus = "active"
    schema_version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def to_firestore(self) -> dict[str, object]:
        return self.__dict__.copy()


@dataclass(frozen=True)
class OAuthTokenRecord:
    user_email: str
    google_sub: str
    allowed_domain: str
    scopes: list[str]
    refresh_token_ciphertext: bytes | None
    refresh_token_kms_key_name: str | None
    status: TokenStatus = "active"
    schema_version: int = 1
    refresh_token_aad_version: str = "v1"
    access_token_ciphertext: bytes | None = None
    access_token_kms_key_name: str | None = None
    access_token_expires_at: datetime | None = None
    last_refresh_at: datetime | None = None
    last_used_at: datetime | None = None
    last_error_class: str | None = None
    reauth_required_reason: str | None = None
    disabled_reason: str | None = None
    deleted_at: datetime | None = None
    expire_at: datetime | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_firestore(self) -> dict[str, object]:
        return self.__dict__.copy()

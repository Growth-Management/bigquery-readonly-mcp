from datetime import UTC, datetime, timedelta

import httpx

from app.oauth_sessions import PersistentSessionError, create_persistent_mcp_session, resolve_persistent_user_session
from app.persistence_models import utc_now


class FakeSettings:
    effective_token_hash_secret = "hash-secret"
    session_ttl_seconds = 3600
    query_timeout_seconds = 60
    kms_key_name = "kms-key"
    oauth_client_id = "client-id"
    oauth_client_secret = "client-secret"


class FakeCipher:
    def __init__(self) -> None:
        self.decrypt_calls = []
        self.encrypt_calls = []

    def decrypt_ciphertext(self, ciphertext, *, kms_key_name=None, aad):
        self.decrypt_calls.append({"ciphertext": ciphertext, "kms_key_name": kms_key_name, "aad": aad})
        if ciphertext == b"refresh-ciphertext":
            return "decrypted-refresh-token"
        return "decrypted-access-token"

    def encrypt(self, plaintext, *, aad):
        self.encrypt_calls.append({"plaintext": plaintext, "aad": aad})

        class Encrypted:
            ciphertext = b"encrypted:" + plaintext.encode()
            kms_key_name = "kms-key"

        return Encrypted()


class FakeTokenResponse:
    def __init__(self, payload, status_code=200) -> None:
        self.payload = payload
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://oauth2.googleapis.com/token")

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            response = httpx.Response(self.status_code, json=self.payload, request=self.request)
            raise httpx.HTTPStatusError("refresh failed", request=self.request, response=response)


class FakeHttpClient:
    def __init__(self, response) -> None:
        self.response = response
        self.post_calls = []

    def post(self, url, *, data, timeout):
        self.post_calls.append({"url": url, "data": data, "timeout": timeout})
        return self.response


class FakeStore:
    def __init__(self) -> None:
        self.saved_sessions = {}
        self.mcp_session = None
        self.token_record = None
        self.token_updates = []

    def save_mcp_session(self, document_id, record):
        self.saved_sessions[document_id] = record

    def get_mcp_session(self, document_id):
        return self.mcp_session

    def get_token_record(self, document_id):
        return self.token_record

    def update_token_record(self, document_id, updates):
        self.token_updates.append({"document_id": document_id, "updates": updates})
        if self.token_record is not None:
            self.token_record.update(updates)


def active_token_record(**overrides):
    record = {
        "status": "active",
        "google_sub": "google-sub",
        "user_email": "user@impress.co.jp",
        "access_token_ciphertext": b"ciphertext",
        "access_token_kms_key_name": "access-key",
        "access_token_expires_at": utc_now() + timedelta(hours=1),
        "refresh_token_ciphertext": b"refresh-ciphertext",
        "refresh_token_kms_key_name": "refresh-key",
    }
    record.update(overrides)
    return record


def test_create_persistent_session_saves_hash_not_raw_token() -> None:
    store = FakeStore()

    response = create_persistent_mcp_session(
        store=store,
        settings=FakeSettings(),
        user_token_record_id="token-doc",
        user_email="user@impress.co.jp",
        google_sub="google-sub",
        scopes=["openid", "email"],
    )

    raw_token = response["access_token"]
    assert isinstance(raw_token, str)
    assert raw_token not in store.saved_sessions
    assert len(store.saved_sessions) == 1
    saved_record = next(iter(store.saved_sessions.values()))
    assert saved_record.user_token_record_id == "token-doc"
    assert saved_record.user_email == "user@impress.co.jp"
    assert response["token_type"] == "Bearer"
    assert response["scope"] == "openid email"


def test_resolve_persistent_session_decrypts_access_token() -> None:
    store = FakeStore()
    store.mcp_session = {"user_token_record_id": "token-doc"}
    store.token_record = active_token_record()
    cipher = FakeCipher()

    session = resolve_persistent_user_session(
        bearer_token="bearer-token",
        store=store,
        settings=FakeSettings(),
        cipher=cipher,
    )

    assert session is not None
    assert session.email == "user@impress.co.jp"
    assert session.access_token == "decrypted-access-token"
    assert session.expires_at > 0
    assert cipher.decrypt_calls == [
        {
            "ciphertext": b"ciphertext",
            "kms_key_name": "access-key",
            "aad": b"bigquery-readonly-mcp:v1:oauth_token_records:token-doc:google-sub",
        }
    ]


def test_resolve_persistent_session_refreshes_expired_access_token() -> None:
    store = FakeStore()
    store.mcp_session = {"user_token_record_id": "token-doc"}
    store.token_record = active_token_record(access_token_expires_at=datetime(2026, 1, 1, tzinfo=UTC))
    cipher = FakeCipher()
    http_client = FakeHttpClient(FakeTokenResponse({"access_token": "new-access-token", "expires_in": 3600, "scope": "openid email profile"}))

    session = resolve_persistent_user_session(
        bearer_token="bearer-token",
        store=store,
        settings=FakeSettings(),
        cipher=cipher,
        http_client=http_client,
    )

    assert session is not None
    assert session.access_token == "new-access-token"
    assert http_client.post_calls == [
        {
            "url": "https://oauth2.googleapis.com/token",
            "data": {
                "client_id": "client-id",
                "client_secret": "client-secret",
                "grant_type": "refresh_token",
                "refresh_token": "decrypted-refresh-token",
            },
            "timeout": 20,
        }
    ]
    assert cipher.decrypt_calls == [
        {
            "ciphertext": b"refresh-ciphertext",
            "kms_key_name": "refresh-key",
            "aad": b"bigquery-readonly-mcp:v1:oauth_token_records:token-doc:google-sub",
        }
    ]
    assert cipher.encrypt_calls == [
        {
            "plaintext": "new-access-token",
            "aad": b"bigquery-readonly-mcp:v1:oauth_token_records:token-doc:google-sub",
        }
    ]
    assert store.token_updates[0]["document_id"] == "token-doc"
    assert store.token_updates[0]["updates"]["access_token_ciphertext"] == b"encrypted:new-access-token"
    assert store.token_updates[0]["updates"]["access_token_kms_key_name"] == "kms-key"
    assert store.token_updates[0]["updates"]["status"] == "active"
    assert store.token_updates[0]["updates"]["scopes"] == ["openid", "email", "profile"]


def test_resolve_persistent_session_marks_reauth_when_refresh_token_missing() -> None:
    store = FakeStore()
    store.mcp_session = {"user_token_record_id": "token-doc"}
    store.token_record = active_token_record(access_token_expires_at=datetime(2026, 1, 1, tzinfo=UTC), refresh_token_ciphertext=None)

    try:
        resolve_persistent_user_session(
            bearer_token="bearer-token",
            store=store,
            settings=FakeSettings(),
            cipher=FakeCipher(),
        )
    except PersistentSessionError as exc:
        assert "missing a refresh token" in str(exc)
    else:
        raise AssertionError("Expected PersistentSessionError")

    assert store.token_updates == [
        {
            "document_id": "token-doc",
            "updates": {
                "status": "reauth_required",
                "reauth_required_reason": "missing_refresh_token",
                "last_error_class": "missing_refresh_token",
            },
        }
    ]


def test_resolve_persistent_session_marks_reauth_on_invalid_grant() -> None:
    store = FakeStore()
    store.mcp_session = {"user_token_record_id": "token-doc"}
    store.token_record = active_token_record(access_token_expires_at=datetime(2026, 1, 1, tzinfo=UTC))
    http_client = FakeHttpClient(FakeTokenResponse({"error": "invalid_grant"}, status_code=400))

    try:
        resolve_persistent_user_session(
            bearer_token="bearer-token",
            store=store,
            settings=FakeSettings(),
            cipher=FakeCipher(),
            http_client=http_client,
        )
    except PersistentSessionError as exc:
        assert "refresh failed" in str(exc)
    else:
        raise AssertionError("Expected PersistentSessionError")

    assert store.token_updates == [
        {
            "document_id": "token-doc",
            "updates": {
                "status": "reauth_required",
                "reauth_required_reason": "invalid_grant",
                "last_error_class": "google_token_refresh_http_error",
            },
        }
    ]


def test_resolve_persistent_session_returns_none_for_missing_session() -> None:
    store = FakeStore()

    assert resolve_persistent_user_session(
        bearer_token="bearer-token",
        store=store,
        settings=FakeSettings(),
        cipher=FakeCipher(),
    ) is None


def test_resolve_persistent_session_rejects_inactive_token_record() -> None:
    store = FakeStore()
    store.mcp_session = {"user_token_record_id": "token-doc"}
    store.token_record = {"status": "disabled"}

    try:
        resolve_persistent_user_session(
            bearer_token="bearer-token",
            store=store,
            settings=FakeSettings(),
            cipher=FakeCipher(),
        )
    except PersistentSessionError as exc:
        assert "not active" in str(exc)
    else:
        raise AssertionError("Expected PersistentSessionError")

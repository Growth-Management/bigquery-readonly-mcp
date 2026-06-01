from datetime import UTC, datetime

from app.oauth_sessions import PersistentSessionError, create_persistent_mcp_session, resolve_persistent_user_session


class FakeSettings:
    effective_token_hash_secret = "hash-secret"
    session_ttl_seconds = 3600
    kms_key_name = "kms-key"


class FakeCipher:
    def __init__(self) -> None:
        self.decrypt_calls = []

    def decrypt_ciphertext(self, ciphertext, *, kms_key_name=None, aad):
        self.decrypt_calls.append({"ciphertext": ciphertext, "kms_key_name": kms_key_name, "aad": aad})
        return "decrypted-access-token"


class FakeStore:
    def __init__(self) -> None:
        self.saved_sessions = {}
        self.mcp_session = None
        self.token_record = None

    def save_mcp_session(self, document_id, record):
        self.saved_sessions[document_id] = record

    def get_mcp_session(self, document_id):
        return self.mcp_session

    def get_token_record(self, document_id):
        return self.token_record


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
    store.token_record = {
        "status": "active",
        "google_sub": "google-sub",
        "user_email": "user@impress.co.jp",
        "access_token_ciphertext": b"ciphertext",
        "refresh_token_kms_key_name": "stored-key",
    }
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
    assert session.expires_at == 0
    assert cipher.decrypt_calls == [
        {
            "ciphertext": b"ciphertext",
            "kms_key_name": "stored-key",
            "aad": b"bigquery-readonly-mcp:v1:oauth_token_records:token-doc:google-sub",
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

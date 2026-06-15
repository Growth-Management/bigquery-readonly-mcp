import time

import pytest

from app.sessions import EncryptedTokenCodec, InMemorySessionStore, get_session_store


def test_in_memory_session_store_returns_active_session() -> None:
    store = InMemorySessionStore()

    session_id = store.create(email="sinohara@impress.co.jp", access_token="token", ttl_seconds=60)
    session = store.get(session_id)

    assert session is not None
    assert session.email == "sinohara@impress.co.jp"
    assert session.access_token == "token"
    assert session.expires_at > time.time()


def test_in_memory_session_store_accepts_refresh_arguments() -> None:
    store = InMemorySessionStore()

    session_id = store.create(
        email="sinohara@impress.co.jp",
        access_token="token",
        refresh_token="refresh-token",
        access_token_expires_in=3600,
        ttl_seconds=60,
    )
    session = store.get(session_id)

    assert session is not None
    assert session.access_token == "token"


def test_in_memory_session_store_drops_expired_session() -> None:
    store = InMemorySessionStore()

    session_id = store.create(email="sinohara@impress.co.jp", access_token="token", ttl_seconds=-1)

    assert store.get(session_id) is None


def test_encrypted_token_codec_round_trips_token() -> None:
    codec = EncryptedTokenCodec("test-session-secret")

    encrypted = codec.encrypt(session_id="session-1", access_token="secret-token")
    decrypted = codec.decrypt(session_id="session-1", **encrypted)

    assert decrypted == "secret-token"
    assert encrypted["access_token_ciphertext"] != "secret-token"


def test_encrypted_token_codec_round_trips_purpose_bound_token() -> None:
    codec = EncryptedTokenCodec("test-session-secret")

    encrypted = codec.encrypt_value(session_id="session-1", purpose="refresh_token", value="secret-refresh-token")
    decrypted = codec.decrypt_value(session_id="session-1", purpose="refresh_token", **encrypted)

    assert decrypted == "secret-refresh-token"
    assert encrypted["ciphertext"] != "secret-refresh-token"


def test_encrypted_token_codec_binds_ciphertext_to_session_id() -> None:
    codec = EncryptedTokenCodec("test-session-secret")

    encrypted = codec.encrypt(session_id="session-1", access_token="secret-token")

    with pytest.raises(Exception):
        codec.decrypt(session_id="session-2", **encrypted)


def test_encrypted_token_codec_binds_ciphertext_to_purpose() -> None:
    codec = EncryptedTokenCodec("test-session-secret")

    encrypted = codec.encrypt_value(session_id="session-1", purpose="refresh_token", value="secret-refresh-token")

    with pytest.raises(Exception):
        codec.decrypt_value(session_id="session-1", purpose="access_token", **encrypted)


def test_get_session_store_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported SESSION_STORE_BACKEND"):
        get_session_store("unknown", "sessions", "test-session-secret", "client-id", "client-secret", 300)

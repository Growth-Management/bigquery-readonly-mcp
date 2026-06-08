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


def test_encrypted_token_codec_binds_ciphertext_to_session_id() -> None:
    codec = EncryptedTokenCodec("test-session-secret")

    encrypted = codec.encrypt(session_id="session-1", access_token="secret-token")

    with pytest.raises(Exception):
        codec.decrypt(session_id="session-2", **encrypted)


def test_get_session_store_rejects_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unsupported SESSION_STORE_BACKEND"):
        get_session_store("unknown", "sessions", "test-session-secret")

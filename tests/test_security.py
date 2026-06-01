from app.security import (
    hash_google_subject,
    mcp_session_id,
    oauth_auth_request_id,
    oauth_authorization_code_id,
    token_aad,
)


def test_google_subject_hash_is_stable_and_unkeyed_document_id() -> None:
    assert hash_google_subject("google-sub-1") == hash_google_subject("google-sub-1")
    assert hash_google_subject("google-sub-1") != hash_google_subject("google-sub-2")


def test_secret_hashes_are_purpose_scoped() -> None:
    secret = "hash-secret"
    raw_value = "same-raw-value"

    auth_request_hash = oauth_auth_request_id(raw_value, secret)
    auth_code_hash = oauth_authorization_code_id(raw_value, secret)
    session_hash = mcp_session_id(raw_value, secret)

    assert auth_request_hash != auth_code_hash
    assert auth_request_hash != session_hash
    assert auth_code_hash != session_hash


def test_secret_hashes_change_with_secret() -> None:
    assert mcp_session_id("token", "secret-1") != mcp_session_id("token", "secret-2")


def test_token_aad_binds_ciphertext_to_document_and_subject() -> None:
    aad = token_aad(document_id="doc-1", google_sub="sub-1")

    assert aad == b"bigquery-readonly-mcp:v1:oauth_token_records:doc-1:sub-1"
    assert token_aad(document_id="doc-2", google_sub="sub-1") != aad
    assert token_aad(document_id="doc-1", google_sub="sub-2") != aad

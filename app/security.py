import hashlib
import hmac


def stable_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def keyed_hash(*, purpose: str, value: str, secret: str) -> str:
    payload = f"{purpose}:v1:{value}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def hash_google_subject(google_sub: str) -> str:
    return stable_sha256(f"v1:{google_sub}")


def oauth_auth_request_id(google_state: str, secret: str) -> str:
    return keyed_hash(purpose="oauth_auth_request", value=google_state, secret=secret)


def oauth_authorization_code_id(auth_code: str, secret: str) -> str:
    return keyed_hash(purpose="oauth_authorization_code", value=auth_code, secret=secret)


def mcp_session_id(bearer_token: str, secret: str) -> str:
    return keyed_hash(purpose="mcp_session", value=bearer_token, secret=secret)


def token_aad(*, document_id: str, google_sub: str) -> bytes:
    aad = f"bigquery-readonly-mcp:v1:oauth_token_records:{document_id}:{google_sub}"
    return aad.encode("utf-8")

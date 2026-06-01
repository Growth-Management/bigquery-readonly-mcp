from functools import lru_cache

from app.config import Settings, get_settings
from app.firestore_store import FirestoreStore
from app.token_crypto import KmsTokenCipher


@lru_cache
def get_store() -> FirestoreStore:
    settings = get_settings()
    return build_store(settings)


def build_store(settings: Settings) -> FirestoreStore:
    return FirestoreStore(
        project_id=settings.effective_firestore_project_id,
        oauth_token_collection=settings.oauth_token_collection,
        oauth_auth_request_collection=settings.oauth_auth_request_collection,
        oauth_authorization_code_collection=settings.oauth_authorization_code_collection,
        mcp_session_collection=settings.mcp_session_collection,
    )


@lru_cache
def get_token_cipher() -> KmsTokenCipher:
    settings = get_settings()
    return build_token_cipher(settings)


def build_token_cipher(settings: Settings) -> KmsTokenCipher:
    if not settings.kms_key_name:
        raise ValueError("KMS_KEY_NAME is required for OAuth persistence")
    return KmsTokenCipher(key_name=settings.kms_key_name)

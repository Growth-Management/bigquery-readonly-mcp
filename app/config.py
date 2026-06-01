from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BigQuery Readonly MCP"
    base_url: str = Field(default="http://localhost:8080", alias="BASE_URL")
    session_secret: str = Field(alias="SESSION_SECRET")
    oauth_client_id: str = Field(alias="GOOGLE_OAUTH_CLIENT_ID")
    oauth_client_secret: str = Field(alias="GOOGLE_OAUTH_CLIENT_SECRET")
    allowed_domain: str = Field(default="impress.co.jp", alias="ALLOWED_DOMAIN")
    default_project_id: str = Field(default="ice-sh", alias="DEFAULT_PROJECT_ID")
    maximum_bytes_billed: int = Field(default=1_073_741_824, alias="MAXIMUM_BYTES_BILLED")
    max_results: int = Field(default=1000, alias="MAX_RESULTS")
    query_timeout_seconds: int = Field(default=60, alias="QUERY_TIMEOUT_SECONDS")
    session_ttl_seconds: int = Field(default=3600, alias="SESSION_TTL_SECONDS")

    firestore_project_id: str | None = Field(default=None, alias="FIRESTORE_PROJECT_ID")
    oauth_token_collection: str = Field(default="oauth_token_records", alias="OAUTH_TOKEN_COLLECTION")
    oauth_auth_request_collection: str = Field(default="oauth_auth_requests", alias="OAUTH_AUTH_REQUEST_COLLECTION")
    oauth_authorization_code_collection: str = Field(
        default="oauth_authorization_codes",
        alias="OAUTH_AUTHORIZATION_CODE_COLLECTION",
    )
    mcp_session_collection: str = Field(default="mcp_sessions", alias="MCP_SESSION_COLLECTION")
    oauth_state_ttl_seconds: int = Field(default=600, alias="OAUTH_STATE_TTL_SECONDS")
    oauth_code_ttl_seconds: int = Field(default=600, alias="OAUTH_CODE_TTL_SECONDS")
    kms_key_name: str | None = Field(default=None, alias="KMS_KEY_NAME")
    token_hash_secret: str | None = Field(default=None, alias="TOKEN_HASH_SECRET")

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth/callback"

    @property
    def effective_firestore_project_id(self) -> str:
        return self.firestore_project_id or self.default_project_id

    @property
    def effective_token_hash_secret(self) -> str:
        return self.token_hash_secret or self.session_secret


@lru_cache
def get_settings() -> Settings:
    return Settings()

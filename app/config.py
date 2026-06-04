from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "BigQuery Readonly MCP"
    base_url: str = Field(default="http://localhost:8080", alias="BASE_URL")
    session_secret: str = Field(alias="SESSION_SECRET")
    oauth_client_id: str = Field(alias="GOOGLE_OAUTH_CLIENT_ID")
    oauth_client_secret: str = Field(alias="GOOGLE_OAUTH_CLIENT_SECRET")
    allowed_domain: str = Field(default="impress.co.jp", alias="ALLOWED_DOMAIN")
    default_project_id: str = Field(default="ice-sh", alias="DEFAULT_PROJECT_ID")
    allowed_project_ids: str = Field(default="", alias="ALLOWED_PROJECT_IDS")
    allowed_user_emails: str = Field(default="", alias="ALLOWED_USER_EMAILS")
    maximum_bytes_billed: int = Field(default=1_073_741_824, alias="MAXIMUM_BYTES_BILLED")
    max_results: int = Field(default=1000, alias="MAX_RESULTS")
    query_timeout_seconds: int = Field(default=60, alias="QUERY_TIMEOUT_SECONDS")
    session_ttl_seconds: int = Field(default=3600, alias="SESSION_TTL_SECONDS")

    @property
    def redirect_uri(self) -> str:
        return f"{self.base_url.rstrip('/')}/oauth/callback"

    @property
    def allowed_project_id_set(self) -> set[str]:
        return _csv_set(self.allowed_project_ids)

    @property
    def allowed_user_email_set(self) -> set[str]:
        return {email.lower() for email in _csv_set(self.allowed_user_emails)}


@lru_cache
def get_settings() -> Settings:
    return Settings()

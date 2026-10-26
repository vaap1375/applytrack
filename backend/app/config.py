from functools import lru_cache
from pydantic import SecretStr, model_validator
from sqlalchemy.engine import make_url
from urllib.parse import urlsplit
from uuid import UUID
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    app_origin: str = ""
    static_dir: str = ""
    migration_database_url: str = ""
    forwarded_allow_ips: str = "127.0.0.1"
    database_url: str = "postgresql+psycopg://applytrack:applytrack@localhost:55432/applytrack"
    supabase_url: str = ""
    owner_id: str = ""
    cors_origins: str = "http://localhost:5173"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    gmail_encryption_key: SecretStr = SecretStr("")
    gmail_redirect_uri: str = "http://localhost:8000/api/gmail/oauth/callback"
    gmail_frontend_url: str = "http://localhost:5173"
    @model_validator(mode="after")
    def production_settings(self):
        if self.app_env not in {"development", "test", "production"}:
            raise ValueError("APP_ENV must be development, test, or production")
        if self.app_env == "production":
            origin = urlsplit(self.app_origin)
            if origin.scheme != "https" or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
                raise ValueError("APP_ORIGIN must be an HTTPS origin without a path")
            if self.cors_origins != self.app_origin:
                raise ValueError("Production CORS_ORIGINS must equal APP_ORIGIN")
            UUID(self.owner_id)
            if not self.supabase_url.startswith("https://"):
                raise ValueError("Production SUPABASE_URL must use HTTPS")
            for value in filter(None, [self.database_url, self.migration_database_url]):
                database = make_url(value)
                if database.get_backend_name() not in {"postgres", "postgresql"} or database.query.get("sslmode") not in {"require", "verify-ca", "verify-full"}:
                    raise ValueError("Production PostgreSQL URLs must require TLS")
            if self.google_client_id or self.google_client_secret.get_secret_value():
                if self.gmail_redirect_uri != self.app_origin + "/api/gmail/oauth/callback" or self.gmail_frontend_url != self.app_origin:
                    raise ValueError("Production Gmail URLs must match APP_ORIGIN")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

@lru_cache
def settings():
    return Settings()

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "CoEv2 Console"
    version: str = "0.1.0"
    database_url: str = "sqlite:///./app.db"  # override via env for Postgres
    council_api_key: str | None = None
    coev2_api_base_url: str = "http://localhost:8765"


settings = Settings()

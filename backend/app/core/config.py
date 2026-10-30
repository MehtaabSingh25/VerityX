from pydantic_settings import BaseSettings, SettingsConfigDict


def normalize_database_url(value: str) -> str:
    """Normalize managed-platform PostgreSQL URLs for psycopg 3."""
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


class Settings(BaseSettings):
    database_url: str
    media_storage_dir: str = "data/media"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    redis_url: str = "redis://localhost:6379/0"
    api_key: str | None = None
    cors_allowed_origins: str = ""

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
settings.database_url = normalize_database_url(settings.database_url)

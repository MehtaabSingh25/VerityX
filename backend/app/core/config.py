from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    media_storage_dir: str = "data/media"
    max_upload_size_bytes: int = 50 * 1024 * 1024
    redis_url: str = "redis://localhost:6379/0"

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()

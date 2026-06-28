"""Application configuration, loaded from environment variables / .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Telegram
    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")

    # OpenAI
    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_gen_model: str = Field("gpt-4o", alias="OPENAI_GEN_MODEL")
    openai_ocr_model: str = Field("gpt-4o", alias="OPENAI_OCR_MODEL")
    openai_embed_model: str = Field("text-embedding-3-small", alias="OPENAI_EMBED_MODEL")

    # RAG / Qdrant — grounds AI exam generation in real past questions.
    rag_enabled: bool = Field(True, alias="RAG_ENABLED")
    qdrant_host: str = Field("qdrant", alias="QDRANT_HOST")
    qdrant_port: int = Field(6333, alias="QDRANT_PORT")
    qdrant_collection: str = Field("konkoor_questions", alias="QDRANT_COLLECTION")

    # Database
    postgres_user: str = Field("exambot", alias="POSTGRES_USER")
    postgres_password: str = Field("exambot_secret", alias="POSTGRES_PASSWORD")
    postgres_db: str = Field("exambot", alias="POSTGRES_DB")
    postgres_host: str = Field("db", alias="POSTGRES_HOST")
    postgres_port: int = Field(5432, alias="POSTGRES_PORT")

    # App behaviour
    default_num_questions: int = Field(30, alias="DEFAULT_NUM_QUESTIONS")
    time_options_minutes: str = Field("10,15,20,30", alias="TIME_OPTIONS_MINUTES")
    log_level: str = Field("INFO", alias="LOG_LEVEL")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy URL (psycopg 3 driver)."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Sync URL used by Alembic migrations."""
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def time_choices(self) -> list[int]:
        return [int(x) for x in self.time_options_minutes.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]

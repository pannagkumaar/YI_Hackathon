import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ---- Phase 1 fields ----
    SHARED_SECRET: str = "dev-secret"
    DIRECTORY_URL: str | None = None
    OVERSEER_URL: str | None = None
    DB_PATH: str = "data/short_term.db"
    ITSM_PATH: str = "data/itsm_data.json"
    DEFAULT_TTL: int = 86400
    SERVICE_NAME: str = "resource-hub"
    SERVICE_BASE_URL: str = "http://127.0.0.1:8000"
    DIRECTORY_TTL: int = 300

    # ---- Phase 2 fields ----
    CHROMA_PERSIST_DIR: str = ":memory:"
    EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
    MAX_CHUNK_SIZE: int = 500
    TOP_K: int = 3

    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-pro"
    MAX_OUTPUT_TOKENS: int = 256

    LOG_LEVEL: str = "INFO"

    # ---- Pydantic v2 config ----
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="allow"  # allow extra vars for forward-compatibility
    )

settings = Settings()
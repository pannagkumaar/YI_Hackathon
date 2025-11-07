import os
from pydantic import BaseModel, Field
from typing import Optional

# Load .env file
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseModel):
    # ---- Phase 1 fields ----
    SHARED_SECRET: str = os.getenv("SHARED_SECRET", "dev-secret")
    DIRECTORY_URL: Optional[str] = os.getenv("DIRECTORY_URL")
    OVERSEER_URL: Optional[str] = os.getenv("OVERSEER_URL")
    DB_PATH: str = os.getenv("DB_PATH", "data/short_term.db")
    ITSM_PATH: str = os.getenv("ITSM_PATH", "data/itsm_data.json")
    DEFAULT_TTL: int = int(os.getenv("DEFAULT_TTL", 86400))
    
    # --- CRITICAL FIX: Match the name other services are looking for ---
    SERVICE_NAME: str = os.getenv("SERVICE_NAME", "resource-hub-service")
    
    SERVICE_BASE_URL: str = os.getenv("SERVICE_BASE_URL", "http://127.0.0.1:8000")
    DIRECTORY_TTL: int = int(os.getenv("DIRECTORY_TTL", 300))

    # ---- Phase 2 fields ----
    CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", ":memory:")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    MAX_CHUNK_SIZE: int = int(os.getenv("MAX_CHUNK_SIZE", 500))
    TOP_K: int = int(os.getenv("TOP_K", 3))

    GOOGLE_API_KEY: Optional[str] = os.getenv("GOOGLE_API_KEY")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-pro")
    MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", 256))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Pydantic v1 Config class
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"

settings = Settings()
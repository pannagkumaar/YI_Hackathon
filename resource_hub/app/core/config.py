import os
import dotenv

# Load .env file from the resource_hub directory
dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
dotenv.load_dotenv(dotenv_path)

class Settings:
    def __init__(self):
        # --- Phase 1 fields ---
        self.SHARED_SECRET: str = os.getenv("SHARED_SECRET", "mysecretapikey") # <-- FIX: Match other services
        self.DIRECTORY_URL: str | None = os.getenv("DIRECTORY_URL")
        self.OVERSEER_URL: str | None = os.getenv("OVERSEER_URL")
        self.DB_PATH: str = os.getenv("DB_PATH", "data/short_term.db")
        self.ITSM_PATH: str = os.getenv("ITSM_PATH", "data/itsm_data.json")
        self.DEFAULT_TTL: int = int(os.getenv("DEFAULT_TTL", 86400))
        self.SERVICE_NAME: str = os.getenv("SERVICE_NAME", "resource-hub-service") # <-- FIX: Match what others discover
        self.SERVICE_BASE_URL: str = os.getenv("SERVICE_BASE_URL", "http://127.0.0.1:8000")
        self.DIRECTORY_TTL: int = int(os.getenv("DIRECTORY_TTL", 300))

        # --- Phase 2 fields ---
        self.CHROMA_PERSIST_DIR: str = os.getenv("CHROMA_PERSIST_DIR", ":memory:")
        self.EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.MAX_CHUNK_SIZE: int = int(os.getenv("MAX_CHUNK_SIZE", 500))
        self.TOP_K: int = int(os.getenv("TOP_K", 3))

        self.GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY")
        self.GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-pro")
        self.MAX_OUTPUT_TOKENS: int = int(os.getenv("MAX_OUTPUT_TOKENS", 256))

        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()
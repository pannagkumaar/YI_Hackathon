# resource_hub/core/config.py
import os

class Settings:
    # Use the global SHIVA env var name
    SHARED_SECRET = os.getenv("SHARED_SECRET", os.getenv("SHIVA_SHARED_SECRET", "dev-secret"))
    DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8005")
    OVERSEER_URL = os.getenv("OVERSEER_URL", "http://localhost:8004")
    DB_PATH = os.getenv("DB_PATH", "data/short_term.db")
    ITSM_PATH = os.getenv("ITSM_PATH", "data/itsm_data.json")
    SERVICE_NAME = os.getenv("SERVICE_NAME", "resource_hub")
    SERVICE_PORT = int(os.getenv("SERVICE_PORT", "8006"))

settings = Settings()

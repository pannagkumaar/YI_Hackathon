import os

class Settings:
    SHARED_SECRET = os.getenv("SHIVA_SHARED_SECRET", "dev-secret")
    DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://localhost:8001")
    OVERSEER_URL = os.getenv("OVERSEER_URL", "http://localhost:8002")
    DB_PATH = os.getenv("DB_PATH", "data/short_term.db")
    ITSM_PATH = os.getenv("ITSM_PATH", "data/itsm_data.json")

settings = Settings()

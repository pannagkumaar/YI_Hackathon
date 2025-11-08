import os
import dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
dotenv.load_dotenv(dotenv_path)

class Settings:
    def __init__(self):
        self.SHARED_SECRET = os.getenv("SHARED_SECRET", "mysecretapikey")
        self.SERVICE_NAME = os.getenv("SERVICE_NAME", "resource-hub-service")
        self.SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://127.0.0.1:8006")
        self.DIRECTORY_URL = os.getenv("DIRECTORY_URL", "http://127.0.0.1:8005")
        self.OVERSEER_URL = os.getenv("OVERSEER_URL", "http://127.0.0.1:8004")

        self.DB_PATH = os.getenv("DB_PATH", "data/short_term.db")
        self.ITSM_PATH = os.getenv("ITSM_PATH", "data/itsm_data.json")
        self.DEFAULT_TTL = int(os.getenv("DEFAULT_TTL", 86400))
        self.DIRECTORY_TTL = int(os.getenv("DIRECTORY_TTL", 300))

        self.CHROMA_PERSIST_DIR = os.getenv(
            "CHROMA_PERSIST_DIR",
            "/home/harini/Harini/GTEHackathon/NEW/YI_Hackathon/resource_hub/chroma_dev"
        )
        self.EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        self.MAX_CHUNK_SIZE = int(os.getenv("MAX_CHUNK_SIZE", 500))
        self.TOP_K = int(os.getenv("TOP_K", 3))

        self.GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
        self.GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-pro")
        self.MAX_OUTPUT_TOKENS = int(os.getenv("MAX_OUTPUT_TOKENS", 256))
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

settings = Settings()

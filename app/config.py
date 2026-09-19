import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

class Settings:
    PROJECT_NAME: str = "ReelToReal AI"
    VERSION: str = "0.1.0"
    
    # Gemini Configuration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "models/gemini-embedding-2")
    
    # Storage settings
    TEMP_VIDEO_DIR: Path = BASE_DIR / os.getenv("TEMP_VIDEO_DIR", "tmp/videos")
    MEDIA_DIR: Path = BASE_DIR / "data/media"
    DB_PATH: Path = BASE_DIR / "data/reeltoreal.db"
    CHROMA_DIR: Path = BASE_DIR / "data/chroma_db"
    EMBEDDING_DIMENSION: int = 768
    
    # Limits
    MAX_UPLOAD_SIZE_MB: int = 50
    YT_DLP_TIMEOUT_SECONDS: int = 30

    @classmethod
    def ensure_directories(cls):
        cls.TEMP_VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        cls.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        cls.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        cls.CHROMA_DIR.mkdir(parents=True, exist_ok=True)

    @classmethod
    def has_gemini_key(cls) -> bool:
        return bool(cls.GEMINI_API_KEY and cls.GEMINI_API_KEY.strip() and cls.GEMINI_API_KEY != "your_gemini_api_key_here")

settings = Settings()
settings.ensure_directories()

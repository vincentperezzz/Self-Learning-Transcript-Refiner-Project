import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# PostgreSQL
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://phoenix:phoenix@localhost:5432/phoenix",
)

# Redis (local caching)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

CORRECTION_THRESHOLD = int(os.getenv("CORRECTION_THRESHOLD", "5"))
LOW_CONFIDENCE_THRESHOLD = float(os.getenv("LOW_CONFIDENCE_THRESHOLD", "0.90"))
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Lightning AI – Remote Whisper endpoint
LIGHTNING_API_URL = os.getenv("LIGHTNING_API_URL", "")
LIGHTNING_API_KEY = os.getenv("LIGHTNING_API_KEY", "")

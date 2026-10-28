import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-change-me")
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "instance" / "attendance.db"))
    FACE_MATCH_THRESHOLD = float(os.getenv("FACE_MATCH_THRESHOLD", "0.50"))
    CAMERA_INDEX = int(os.getenv("CAMERA_INDEX", "0"))
    CAMERA_SCAN_INTERVAL_MS = int(os.getenv("CAMERA_SCAN_INTERVAL_MS", "1000"))
    RECOGNITION_COOLDOWN_SECONDS = int(os.getenv("RECOGNITION_COOLDOWN_SECONDS", "30"))
    APP_NAME = os.getenv("APP_NAME", "Nivora")
    SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "60"))
    MAX_CONTENT_LENGTH = 4 * 1024 * 1024

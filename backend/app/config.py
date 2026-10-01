from pathlib import Path
import os
import secrets

BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings:
    # Use existing SQLite from Flask app — share schema + data
    DATABASE_URL: str = os.environ.get("DATABASE_URL") or f"sqlite:///{BASE_DIR / 'golf.db'}"
    SECRET_KEY: str = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
    JWT_ALG: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 8
    COOKIE_NAME: str = "golf_session"
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    CLUB_NAME: str = os.environ.get("CLUB_NAME", "Крылатское")
    CLUB_TIMEZONE: str = "Europe/Moscow"
    OPENING_HOUR: int = 8
    CLOSING_HOUR: int = 22
    SLOT_MINUTES: int = 30


settings = Settings()

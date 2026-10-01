import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or f"sqlite:///{BASE_DIR / 'golf.db'}"
    SQLALCHEMY_ECHO = False
    WTF_CSRF_TIME_LIMIT = None  # CSRF valid for session lifetime
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 8  # 8h
    CLUB_NAME = os.environ.get('CLUB_NAME', 'МГГК · Крылатское')
    CLUB_TIMEZONE = 'Europe/Moscow'
    OPENING_HOUR = 8
    CLOSING_HOUR = 22
    SLOT_MINUTES = 30

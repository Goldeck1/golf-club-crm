"""Аутентификация, хеширование паролей, RBAC-декораторы."""
from __future__ import annotations
import hashlib
from functools import wraps
from flask import abort, flash, redirect, url_for
from flask_login import current_user
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

from ..db import get_session
from ..domain import User, UserRole

_hasher = PasswordHasher()


def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(user: User, raw: str) -> bool:
    """Проверяет пароль. Поддерживает миграцию со старого SHA-256 на лету."""
    if not user or not user.password_hash:
        return False
    pw_hash = user.password_hash

    # 1. Legacy SHA-256 (ровно 64 hex-символа)
    if len(pw_hash) == 64 and all(c in '0123456789abcdef' for c in pw_hash):
        if hashlib.sha256(raw.encode()).hexdigest() == pw_hash:
            # прозрачная миграция на argon2
            user.password_hash = _hasher.hash(raw)
            get_session().commit()
            return True
        return False

    # 2. Argon2
    try:
        if _hasher.verify(pw_hash, raw):
            if _hasher.check_needs_rehash(pw_hash):
                user.password_hash = _hasher.hash(raw)
                get_session().commit()
            return True
    except (VerifyMismatchError, InvalidHash):
        return False
    return False


# ─── RBAC ───────────────────────────────────────────────────────────

def _require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('auth.login'))
            if current_user.role not in roles:
                flash('Доступ запрещён для вашей роли', 'error')
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def admin_required(f):
    return _require_roles(UserRole.ADMIN.value)(f)


def manager_required(f):
    return _require_roles(UserRole.ADMIN.value, UserRole.MANAGER.value)(f)


def accounting_required(f):
    return _require_roles(UserRole.ADMIN.value, UserRole.ACCOUNTING.value)(f)


def staff_or_above(f):
    """Любой аутентифицированный пользователь."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return wrapper

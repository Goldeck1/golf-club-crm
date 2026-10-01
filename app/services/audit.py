"""Запись в AuditLog. Вызывается из booking_service и других."""
from __future__ import annotations
from typing import Optional, Any
from flask import request
from flask_login import current_user

from ..db import get_session
from ..domain import AuditLog


def _serialize(obj: Any) -> dict:
    """Дамп ORM-объекта в простой dict (только плоские поля)."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return obj
    d = {}
    for col in obj.__table__.columns:
        v = getattr(obj, col.name, None)
        if hasattr(v, 'isoformat'):
            v = v.isoformat()
        d[col.name] = v
    return d


def log(
    action: str,
    entity: str,
    entity_id: Optional[int] = None,
    summary: str = '',
    before: Any = None,
    after: Any = None,
):
    session = get_session()
    actor_id = current_user.id if getattr(current_user, 'is_authenticated', False) else None
    actor_name = current_user.username if getattr(current_user, 'is_authenticated', False) else 'system'
    try:
        ip = request.remote_addr or ''
    except RuntimeError:   # outside request context
        ip = ''

    entry = AuditLog(
        action=action,
        entity=entity,
        entity_id=entity_id,
        actor_user_id=actor_id,
        actor_username=actor_name,
        summary=summary,
        before=_serialize(before),
        after=_serialize(after),
        ip=ip,
    )
    session.add(entry)
    # commit делает внешний вызов (в одной транзакции с основным изменением)

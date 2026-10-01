"""Глобальный поиск — палитра Cmd+K. Кириллицу SQLite не свёртывает, фильтр в Python."""
from flask import Blueprint, jsonify, request, url_for
from flask_login import login_required
from sqlalchemy import select

from ..db import get_session
from ..domain import Customer, Booking, Service, Instructor

bp = Blueprint('search', __name__)


def _contains(haystack: str, needle: str) -> bool:
    return needle.casefold() in (haystack or '').casefold()


@bp.route('/api/search')
@login_required
def search():
    s = get_session()
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])

    results = []

    # Брони — по ID в первую очередь
    if q.isdigit():
        b = s.get(Booking, int(q))
        if b:
            results.append({
                'kind': 'booking',
                'icon': 'bookmark',
                'title': f'Бронь #{b.id}',
                'subtitle': (b.customer.name if b.customer else 'Без клиента') +
                            f' · {b.starts_at.strftime("%d.%m %H:%M")}',
                'url': url_for('calendar.index', date=b.starts_at.date().isoformat()),
            })

    # Клиенты
    customers = s.execute(select(Customer)).scalars().all()
    matched_c = [
        c for c in customers
        if _contains(c.name, q) or _contains(c.phone, q) or _contains(c.email, q)
    ][:6]
    for c in matched_c:
        results.append({
            'kind': 'client', 'icon': 'user',
            'title': c.name,
            'subtitle': c.phone or c.email or '—',
            'url': url_for('customers.detail', cid=c.id),
        })

    # Тренеры
    instructors = s.execute(select(Instructor).where(Instructor.active == True)).scalars().all()
    matched_i = [i for i in instructors if _contains(i.name, q) or _contains(i.specialization, q)][:4]
    for i in matched_i:
        results.append({
            'kind': 'instructor', 'icon': 'user-cog',
            'title': i.name,
            'subtitle': i.specialization or 'Тренер',
            'url': url_for('catalog.edit_instructor', iid=i.id),
        })

    # Услуги
    services = s.execute(select(Service).where(Service.active == True)).scalars().all()
    matched_s = [sv for sv in services if _contains(sv.name, q) or _contains(sv.category, q)][:4]
    for svc in matched_s:
        results.append({
            'kind': 'service', 'icon': 'tag',
            'title': svc.name,
            'subtitle': f'{svc.category} · {svc.base_price_kopecks // 100} ₽',
            'url': url_for('catalog.edit_service', sid=svc.id),
        })

    return jsonify(results)

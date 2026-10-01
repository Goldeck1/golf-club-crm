"""Cascade preview & apply: что изменится при смене цены услуги или настройки тренера.

Правило immutability: paid/partially_refunded/refunded/canceled — never touch.
Pending (unpaid) и draft — можно пересчитать при согласии админа.
Completed без оплаты — замораживаем (уже по факту оказаны).
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from sqlalchemy import select

from ..db import get_session
from ..domain.models import Booking, Service, BookingStatus, PaymentStatus


MUTABLE_PAYMENT = {PaymentStatus.PENDING.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELED.value}
# Бронирования, которые можно пересчитать: будущие и ещё не оплаченные
FUTURE_STATUSES = {
    BookingStatus.DRAFT.value,
    BookingStatus.HELD.value,
    BookingStatus.CONFIRMED.value,
}


def preview_service_price_change(
    service_id: int,
    new_base_price_kopecks: int,
    *,
    only_future: bool = True,
) -> dict:
    """
    Предпросмотр: если сменить base_price услуги — что изменится?

    Возвращает:
    {
        'service_id': ..., 'old_price': ..., 'new_price': ..., 'delta_per_booking': ...,
        'affected_bookings': [
            {'id': ..., 'starts_at': ..., 'customer_name': ..., 'old_total': ..., 'new_total': ...}
        ],
        'frozen_bookings_count': N,   # оплаченные — не трогаем
        'total_delta_kopecks': ...,    # сколько поменяется в сумме
    }
    """
    s = get_session()
    service = s.get(Service, service_id)
    if not service:
        return {'error': 'service_not_found'}

    old = service.base_price_kopecks
    delta = new_base_price_kopecks - old
    now = datetime.utcnow()

    q = select(Booking).where(Booking.service_id == service_id)
    if only_future:
        q = q.where(Booking.starts_at > now)

    all_bookings = list(s.execute(q).scalars())

    affected = []
    frozen = 0
    for b in all_bookings:
        if (
            b.status in FUTURE_STATUSES
            and b.payment_status in MUTABLE_PAYMENT
        ):
            # применяем delta пропорционально (на случай если price != base)
            new_total = max(0, b.total_kopecks + delta * (b.guests or 1))
            affected.append({
                'id': b.id,
                'starts_at': b.starts_at.isoformat(),
                'customer_name': b.customer.name if b.customer else '—',
                'old_total': b.total_kopecks,
                'new_total': new_total,
                'delta': new_total - b.total_kopecks,
            })
        else:
            frozen += 1

    return {
        'service_id': service_id,
        'service_name': service.name,
        'old_price_kopecks': old,
        'new_price_kopecks': new_base_price_kopecks,
        'delta_per_booking': delta,
        'affected_bookings': affected,
        'affected_count': len(affected),
        'frozen_bookings_count': frozen,
        'total_delta_kopecks': sum(a['delta'] for a in affected),
    }


def apply_service_price_change(
    service_id: int,
    new_base_price_kopecks: int,
    *,
    also_apply_to_bookings: bool = False,
) -> dict:
    """
    Применить изменение цены.
    - service.base_price всегда обновляется
    - если also_apply_to_bookings=True — пересчитываются future+unpaid брони
    - исторические (paid/completed) НЕ трогаются никогда (immutability)
    """
    from . import audit
    s = get_session()
    service = s.get(Service, service_id)
    if not service:
        return {'error': 'service_not_found'}

    old_price = service.base_price_kopecks
    service.base_price_kopecks = new_base_price_kopecks

    updated_count = 0
    if also_apply_to_bookings:
        preview = preview_service_price_change(service_id, new_base_price_kopecks)
        for item in preview['affected_bookings']:
            b = s.get(Booking, item['id'])
            b.price_kopecks = b.price_kopecks + preview['delta_per_booking'] * (b.guests or 1)
            b.total_kopecks = item['new_total']
            updated_count += 1

    audit.log(
        'update', 'service', service_id,
        summary=f'Цена услуги: {old_price // 100} → {new_base_price_kopecks // 100} ₽' +
                (f' (пересчитано {updated_count} броней)' if also_apply_to_bookings else ''),
        before={'base_price_kopecks': old_price},
        after={'base_price_kopecks': new_base_price_kopecks},
    )
    s.commit()
    return {'ok': True, 'updated_bookings': updated_count}

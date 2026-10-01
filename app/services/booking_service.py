"""Бизнес-логика жизненного цикла брони с аудит-логом."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from sqlalchemy import select
from flask_login import current_user

from ..db import get_session
from ..domain import (
    Booking, BookingItem, BookingStatus, PaymentStatus, Customer, Service,
    AuditAction,
)
from . import audit
from .scheduler import find_conflicts


class SchedulerConflict(Exception):
    """Бросается, когда новая бронь пересекается с существующей."""
    def __init__(self, conflicts: list):
        self.conflicts = conflicts
        super().__init__(f'Конфликт c {len(conflicts)} бронями')


# ─── Создание ───────────────────────────────────────────────────────

def create_booking(
    *,
    resource_id: Optional[int],
    service_id: Optional[int],
    customer_id: Optional[int],
    instructor_id: Optional[int],
    starts_at: datetime,
    ends_at: datetime,
    guests: int = 1,
    with_guest: bool = False,
    price_kopecks: int = 0,
    discount_kopecks: int = 0,
    comment: str = '',
    status: str = BookingStatus.CONFIRMED.value,
    check_conflicts: bool = True,
) -> Booking:
    s = get_session()

    if check_conflicts and resource_id:
        conflicts = find_conflicts(resource_id, starts_at, ends_at)
        if conflicts:
            raise SchedulerConflict(conflicts)

    total = max(0, price_kopecks - discount_kopecks)
    booking = Booking(
        resource_id=resource_id,
        service_id=service_id,
        customer_id=customer_id,
        instructor_id=instructor_id,
        starts_at=starts_at,
        ends_at=ends_at,
        guests=guests,
        with_guest=with_guest,
        status=status,
        payment_status=PaymentStatus.PENDING.value,
        price_kopecks=price_kopecks,
        discount_kopecks=discount_kopecks,
        total_kopecks=total,
        comment=comment,
        created_by_id=current_user.id if getattr(current_user, 'is_authenticated', False) else None,
    )
    s.add(booking)
    s.flush()

    # Строка услуги в BookingItem
    if service_id:
        service = s.get(Service, service_id)
        if service:
            s.add(BookingItem(
                booking_id=booking.id,
                kind='service',
                service_id=service_id,
                name=service.name,
                quantity=guests or 1,
                unit_price_kopecks=service.base_price_kopecks,
                total_kopecks=price_kopecks,
            ))

    audit.log(
        AuditAction.CREATE.value, 'booking', booking.id,
        summary=f'Создана бронь #{booking.id}',
        after=booking,
    )
    s.commit()
    return booking


# ─── Переходы статусов ──────────────────────────────────────────────

_ALLOWED_TRANSITIONS = {
    BookingStatus.DRAFT.value:       {BookingStatus.HELD.value, BookingStatus.CONFIRMED.value, BookingStatus.CANCELLED.value},
    BookingStatus.HELD.value:        {BookingStatus.CONFIRMED.value, BookingStatus.CANCELLED.value},
    BookingStatus.CONFIRMED.value:   {BookingStatus.CHECKED_IN.value, BookingStatus.CANCELLED.value, BookingStatus.NO_SHOW.value, BookingStatus.COMPLETED.value},
    BookingStatus.CHECKED_IN.value:  {BookingStatus.COMPLETED.value, BookingStatus.CANCELLED.value},
    BookingStatus.COMPLETED.value:   set(),
    BookingStatus.CANCELLED.value:   set(),
    BookingStatus.NO_SHOW.value:     {BookingStatus.COMPLETED.value},  # кассир всё же пробил
}


def _transition(booking: Booking, to_status: str, action: str, reason: str = ''):
    s = get_session()
    if to_status not in _ALLOWED_TRANSITIONS[booking.status]:
        raise ValueError(f'Переход {booking.status} → {to_status} запрещён')
    before_snapshot = {'status': booking.status, 'payment_status': booking.payment_status}
    booking.status = to_status

    now = datetime.utcnow()
    if to_status == BookingStatus.CHECKED_IN.value:
        booking.checked_in_at = now
    elif to_status == BookingStatus.COMPLETED.value:
        booking.completed_at = now
    elif to_status == BookingStatus.CANCELLED.value:
        booking.cancelled_at = now
        booking.cancel_reason = reason
    elif to_status == BookingStatus.NO_SHOW.value:
        booking.no_show_at = now

    audit.log(
        action, 'booking', booking.id,
        summary=f'{before_snapshot["status"]} → {to_status}' + (f' ({reason})' if reason else ''),
        before=before_snapshot,
        after={'status': booking.status},
    )
    s.commit()
    return booking


def confirm(booking: Booking):
    return _transition(booking, BookingStatus.CONFIRMED.value, AuditAction.STATUS_CHANGE.value)

def check_in(booking: Booking):
    return _transition(booking, BookingStatus.CHECKED_IN.value, AuditAction.CHECK_IN.value)

def complete(booking: Booking):
    return _transition(booking, BookingStatus.COMPLETED.value, AuditAction.COMPLETE.value)

def cancel(booking: Booking, reason: str = ''):
    return _transition(booking, BookingStatus.CANCELLED.value, AuditAction.CANCEL.value, reason)

def mark_no_show(booking: Booking):
    return _transition(booking, BookingStatus.NO_SHOW.value, AuditAction.NO_SHOW.value)


# ─── Оплата ─────────────────────────────────────────────────────────

def mark_paid(booking: Booking, method: str = 'cash'):
    s = get_session()
    before = {'payment_status': booking.payment_status}
    booking.payment_status = PaymentStatus.PAID.value
    audit.log(
        AuditAction.PAYMENT.value, 'booking', booking.id,
        summary=f'Оплата {booking.total_kopecks // 100}₽ ({method})',
        before=before,
        after={'payment_status': booking.payment_status, 'method': method},
    )
    s.commit()


# ─── Перенос (drag-and-drop на сетке) ───────────────────────────────

def reschedule(
    booking: Booking,
    *,
    resource_id: Optional[int] = None,
    starts_at: Optional[datetime] = None,
    ends_at: Optional[datetime] = None,
):
    s = get_session()
    before = {
        'resource_id': booking.resource_id,
        'starts_at': booking.starts_at.isoformat(),
        'ends_at': booking.ends_at.isoformat(),
    }
    new_resource = resource_id or booking.resource_id
    new_start = starts_at or booking.starts_at
    new_end = ends_at or booking.ends_at

    conflicts = find_conflicts(new_resource, new_start, new_end, exclude_booking_id=booking.id)
    if conflicts:
        raise SchedulerConflict(conflicts)

    booking.resource_id = new_resource
    booking.starts_at = new_start
    booking.ends_at = new_end

    audit.log(
        AuditAction.UPDATE.value, 'booking', booking.id,
        summary='Перенос',
        before=before,
        after={
            'resource_id': booking.resource_id,
            'starts_at': booking.starts_at.isoformat(),
            'ends_at': booking.ends_at.isoformat(),
        },
    )
    s.commit()
    return booking

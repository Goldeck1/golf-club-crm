"""Resource scheduler: слоты, правила доступности, проверка пересечений."""
from __future__ import annotations
from datetime import datetime, date, time, timedelta
from typing import List, Optional, Tuple
from sqlalchemy import and_, or_, select

from ..db import get_session
from ..domain import (
    Resource, AvailabilityRule, Blackout, Booking, BookingStatus, Season,
)


# ─── Определение текущего сезона ────────────────────────────────────

def current_season(at: Optional[date] = None) -> str:
    at = at or date.today()
    # май-сентябрь = summer
    return Season.SUMMER.value if 5 <= at.month <= 9 else Season.WINTER.value


# ─── Рабочие часы ресурса ───────────────────────────────────────────

def resource_hours(resource: Resource, on: date) -> Tuple[time, time]:
    """
    Возвращает (open, close) для ресурса на дату. Ищет первое подходящее правило;
    если нет — берёт часы клуба из config (через AppSetting или дефолты).
    """
    season = current_season(on)
    weekday = on.weekday()
    for rule in resource.availability_rules:
        if rule.valid_from and on < rule.valid_from:
            continue
        if rule.valid_to and on > rule.valid_to:
            continue
        if rule.season not in (Season.ALL_YEAR.value, season):
            continue
        if rule.weekday is not None and rule.weekday != weekday:
            continue
        open_t = time.fromisoformat(rule.open_time)
        close_t = time.fromisoformat(rule.close_time)
        return (open_t, close_t)
    # default
    return (time(8, 0), time(22, 0))


def is_in_blackout(resource_id: int, starts_at: datetime, ends_at: datetime) -> Optional[Blackout]:
    s = get_session()
    q = select(Blackout).where(
        or_(Blackout.resource_id == resource_id, Blackout.resource_id.is_(None)),
        Blackout.starts_at < ends_at,
        Blackout.ends_at > starts_at,
    )
    return s.execute(q).scalar_one_or_none()


# ─── Проверка пересечений ──────────────────────────────────────────

def find_conflicts(
    resource_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_booking_id: Optional[int] = None,
) -> List[Booking]:
    """Возвращает список активных броней на этом ресурсе, пересекающихся с окном."""
    s = get_session()
    active_statuses = (
        BookingStatus.HELD.value,
        BookingStatus.CONFIRMED.value,
        BookingStatus.CHECKED_IN.value,
    )
    q = select(Booking).where(
        Booking.resource_id == resource_id,
        Booking.status.in_(active_statuses),
        Booking.starts_at < ends_at,
        Booking.ends_at > starts_at,
    )
    if exclude_booking_id:
        q = q.where(Booking.id != exclude_booking_id)
    return list(s.execute(q).scalars())


def is_slot_free(
    resource_id: int,
    starts_at: datetime,
    ends_at: datetime,
    exclude_booking_id: Optional[int] = None,
) -> bool:
    return not find_conflicts(resource_id, starts_at, ends_at, exclude_booking_id)


# ─── Генерация слотов ──────────────────────────────────────────────

def slots_for_day(
    resource: Resource,
    on: date,
    step_minutes: int = 30,
) -> List[dict]:
    """Генерирует все слоты на день для ресурса с пометкой свободен/занят/blackout."""
    open_t, close_t = resource_hours(resource, on)
    day_start = datetime.combine(on, open_t)
    day_end = datetime.combine(on, close_t)

    s = get_session()
    existing = s.execute(
        select(Booking).where(
            Booking.resource_id == resource.id,
            Booking.status.in_([
                BookingStatus.HELD.value,
                BookingStatus.CONFIRMED.value,
                BookingStatus.CHECKED_IN.value,
            ]),
            Booking.starts_at < day_end,
            Booking.ends_at > day_start,
        )
    ).scalars().all()
    blackouts = s.execute(
        select(Blackout).where(
            or_(Blackout.resource_id == resource.id, Blackout.resource_id.is_(None)),
            Blackout.starts_at < day_end,
            Blackout.ends_at > day_start,
        )
    ).scalars().all()

    slots = []
    cursor = day_start
    while cursor < day_end:
        slot_end = cursor + timedelta(minutes=step_minutes)
        # statusy
        in_blackout = any(b.starts_at < slot_end and b.ends_at > cursor for b in blackouts)
        booking = next(
            (b for b in existing if b.starts_at < slot_end and b.ends_at > cursor),
            None,
        )
        slots.append({
            'resource_id': resource.id,
            'starts_at': cursor,
            'ends_at': slot_end,
            'state': (
                'blackout' if in_blackout
                else 'booked' if booking
                else 'free'
            ),
            'booking_id': booking.id if booking else None,
        })
        cursor = slot_end
    return slots


# ─── Ресурсы видимые в текущем сезоне ───────────────────────────────

def visible_resources() -> List[Resource]:
    s = get_session()
    season = current_season()
    q = select(Resource).where(
        Resource.active == True,
        Resource.season.in_([Season.ALL_YEAR.value, season]),
    ).order_by(Resource.sort_order, Resource.name)
    return list(s.execute(q).scalars())

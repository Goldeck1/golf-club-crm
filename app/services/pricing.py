"""Расчёт цены с учётом:
- базовая цена услуги
- override от тренера (InstructorServicePrice)
- правила ServicePricing (день недели / время / сезон / tier клиента)
- скидка по активному членству клиента

Иерархия приоритетов: membership discount > ServicePricing rule > instructor override > base.
"""
from __future__ import annotations
from datetime import date, datetime, time
from typing import Optional
from sqlalchemy import select

from ..db import get_session
from ..domain.models import (
    Service, Instructor, InstructorServicePrice, ServicePricing,
    Customer, Membership, MembershipPlan, Season,
)


def _active_membership_tier(customer_id: Optional[int]) -> tuple[int, int]:
    """Возвращает (tier, discount_percent) активного членства или (0, 0)."""
    if not customer_id:
        return (0, 0)
    s = get_session()
    today = date.today()
    q = (
        select(Membership, MembershipPlan)
        .join(MembershipPlan, MembershipPlan.id == Membership.plan_id)
        .where(
            Membership.customer_id == customer_id,
            Membership.active == True,
            Membership.starts_on <= today,
            Membership.ends_on >= today,
        )
        .order_by(MembershipPlan.tier.desc())
        .limit(1)
    )
    row = s.execute(q).first()
    if not row:
        return (0, 0)
    _, plan = row
    return (plan.tier, plan.discount_percent)


def instructor_override_price(instructor_id: int, service_id: int) -> Optional[int]:
    """Возвращает кастомный прайс тренера за услугу (kopecks) или None."""
    s = get_session()
    row = s.execute(
        select(InstructorServicePrice).where(
            InstructorServicePrice.instructor_id == instructor_id,
            InstructorServicePrice.service_id == service_id,
            InstructorServicePrice.active == True,
        )
    ).scalar_one_or_none()
    return row.price_kopecks if row else None


def _find_pricing_rule(
    service_id: int,
    at: datetime,
    season: str,
    member_tier: int,
) -> Optional[int]:
    """Находит подходящее правило ценообразования, возвращает цену или None."""
    s = get_session()
    weekday = at.weekday()
    hm = at.strftime('%H:%M')

    rules = s.execute(
        select(ServicePricing).where(
            ServicePricing.service_id == service_id,
            ServicePricing.active == True,
        ).order_by(ServicePricing.priority.desc())
    ).scalars().all()

    for rule in rules:
        # weekday
        if rule.weekdays and weekday not in rule.weekdays:
            continue
        # time window
        if rule.time_from and hm < rule.time_from:
            continue
        if rule.time_to and hm > rule.time_to:
            continue
        # season
        if rule.season not in (Season.ALL_YEAR.value, season):
            continue
        # tier
        if member_tier < rule.member_tier_min:
            continue
        return rule.price_kopecks
    return None


def calc_price_kopecks(
    *,
    service: Service,
    starts_at: datetime,
    instructor: Optional[Instructor] = None,
    customer_id: Optional[int] = None,
    guests: int = 1,
    season: Optional[str] = None,
) -> dict:
    """
    Рассчитывает итоговую цену для брони.

    Возвращает структурированный разбор:
    {
        'base_kopecks': ...,
        'applied_rule': 'base' | 'instructor_override' | 'pricing_rule' | 'membership_discount',
        'explanation': [строки разбора],
        'subtotal_kopecks': ...,
        'discount_kopecks': ...,
        'total_kopecks': ...,
    }
    """
    from .scheduler import current_season as _cs
    season = season or _cs(starts_at.date())

    base = service.base_price_kopecks
    subtotal = base
    explanation = [f'База услуги «{service.name}»: {base // 100} ₽']

    # 1. Instructor override
    if instructor:
        override = instructor_override_price(instructor.id, service.id)
        if override is not None and override != base:
            subtotal = override
            explanation.append(f'Override тренера {instructor.name}: {override // 100} ₽')

    # 2. ServicePricing rule
    tier, discount_pct = _active_membership_tier(customer_id)
    rule_price = _find_pricing_rule(service.id, starts_at, season, tier)
    if rule_price is not None:
        subtotal = rule_price
        weekday_name = ['пн','вт','ср','чт','пт','сб','вс'][starts_at.weekday()]
        explanation.append(f'Правило прайса (день {weekday_name}, {starts_at.strftime("%H:%M")}): {rule_price // 100} ₽')

    # 3. Membership discount
    discount = 0
    if discount_pct > 0:
        discount = subtotal * discount_pct // 100
        explanation.append(f'Скидка по членству ({discount_pct}%): −{discount // 100} ₽')

    total = max(0, subtotal - discount)

    return {
        'base_kopecks': base,
        'subtotal_kopecks': subtotal,
        'discount_kopecks': discount,
        'total_kopecks': total,
        'explanation': explanation,
        'member_tier': tier,
    }

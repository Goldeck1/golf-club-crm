"""Scenario-based booking resolver.

Translates admin-facing scenario input (category / guests / training type /
trainer / time) into internal service+resource+price payload and validates
capacity + trainer conflicts.

The price tables here are the SINGLE SOURCE OF TRUTH for scenario bookings.
Frontend only shows what this module computes.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from .enums import BookingStatus
from .models import Booking, Resource, Service, Instructor, Coupon, Membership, MembershipPlan


# ─────────────────────────── tariff tables ─────────────────────────────

BookingCategory = Literal[
    "range_weekday_basket",
    "range_weekend_hour",
    "hole_19_20",
]

TrainingType = Literal["trial", "regular", "kids"]

CATEGORY_CATALOG: dict[str, dict] = {
    "range_weekday_basket": {
        "sku": "driving-basket-40-weekday",
        "title": "Range · будни · 1 корзина (40 мячей)",
        "short": "Range (будни)",
        "detail": "1 корзина 40 мячей",
        "base_price_kopecks": 150000,
        "duration_min": 60,
        "resource_pool": "range",
        "pool_capacity": 24,
        # for this category admin can order N baskets, base *= baskets
        "basket_unit": True,
        "basket_unit_label": "корзина",
        "per_guest": False,
    },
    "range_weekend_hour": {
        "sku": "driving-1h-weekend",
        "title": "Range · выходные · 1 час (мячи без лимита)",
        "short": "Range (выходные)",
        "detail": "1 час, мячи без лимита",
        "base_price_kopecks": 300000,
        "duration_min": 60,
        "resource_pool": "range",
        "pool_capacity": 24,
        "basket_unit": False,
        "basket_unit_label": "",
        # On weekends the tariff is per guest (unlimited balls for each guest).
        "per_guest": True,
    },
    "hole_19_20": {
        "sku": "academic-holes-19-20",
        "title": "Лунка 19, 20",
        "short": "Лунка 19, 20",
        "detail": "Академические лунки",
        "base_price_kopecks": 200000,
        "duration_min": 60,
        "resource_pool": "hole_19_20",
        "pool_capacity": 1,
        "basket_unit": False,
        "basket_unit_label": "",
        "per_guest": False,
    },
}


# Training matrix: (type, guests) -> (sku, price_kopecks).
# Values are exact, NOT a unit × guests formula (per spec).
TRAINING_MATRIX: dict[tuple[str, int], tuple[str, int]] = {
    ("trial", 1): ("trial-lesson-1", 700000),
    ("trial", 2): ("trial-lesson-2", 1000000),
    ("trial", 3): ("trial-lesson-3", 1200000),
    ("trial", 4): ("trial-lesson-4", 1400000),
    ("regular", 1): ("lesson-1", 1000000),
    ("regular", 2): ("lesson-2", 1400000),
    ("regular", 3): ("lesson-3", 1800000),
    ("regular", 4): ("lesson-4", 2100000),
    ("kids", 1): ("kids-lesson-1", 700000),
    ("kids", 2): ("kids-lesson-2", 1000000),
    ("kids", 3): ("kids-lesson-3", 1200000),
    ("kids", 4): ("kids-lesson-4", 1400000),
}

TRAINING_TYPE_LABELS = {
    "trial": "Пробная тренировка",
    "regular": "Обычная тренировка",
    "kids": "Детская тренировка",
}

# SKU codes used as markers for range/hole pools in the Resource catalog.
# МГГК operates 24 driving-range bays (D1..D24).
RANGE_RESOURCE_CODES = {f"D{i}" for i in range(1, 25)}
HOLE_19_20_CODES = {"H19", "H20"}


# ─────────────────────────── DTOs ─────────────────────────────


@dataclass
class ScenarioInput:
    category: str
    guests: int
    has_training: bool
    training_type: Optional[str]
    trainer_id: Optional[int]
    starts_at: datetime
    ends_at: datetime
    customer_id: Optional[int]
    comment: str
    exclude_booking_id: Optional[int] = None
    # For categories that bill per basket (currently range_weekday_basket).
    # Ignored for other categories. Must be >= 1 when applicable.
    baskets: int = 1
    # Optional promocode (Coupon.code). Applied after base+training sum.
    coupon_code: str = ""
    # Optional active membership id (Membership.id). Applies plan.discount_percent
    # to the booking subtotal before coupon (coupon stacks on top).
    membership_id: Optional[int] = None


@dataclass
class Availability:
    ok: bool
    message: str


@dataclass
class ResolvedScenario:
    ok: bool
    errors: list[str]
    warnings: list[str]

    # price
    base_price_kopecks: int
    training_price_kopecks: int
    total_kopecks: int

    # labels for UI
    category_title: str
    category_short: str
    category_detail: str
    training_label: str
    trainer_name: str

    # capacity/availability statuses
    resource_availability: Availability
    trainer_availability: Availability

    # resolved ids (null when validation failed at that step)
    base_service_id: Optional[int]
    training_service_id: Optional[int]
    resource_id: Optional[int]
    duration_min: int

    # basket-unit support (only for range_weekday_basket)
    basket_unit: bool = False
    basket_unit_label: str = ""
    baskets: int = 1
    basket_unit_price_kopecks: int = 0

    # discount layer (promocode + membership)
    subtotal_kopecks: int = 0          # base + training, before any discount
    membership_discount_kopecks: int = 0
    coupon_discount_kopecks: int = 0
    discount_kopecks: int = 0
    coupon_code: str = ""              # validated code (empty if invalid/missing)
    coupon_label: str = ""             # e.g. "SUMMER10 (−10%)"
    coupon_error: str = ""
    membership_label: str = ""         # e.g. "Gold (−15%)"

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "base_price_kopecks": self.base_price_kopecks,
            "training_price_kopecks": self.training_price_kopecks,
            "total_kopecks": self.total_kopecks,
            "category_title": self.category_title,
            "category_short": self.category_short,
            "category_detail": self.category_detail,
            "training_label": self.training_label,
            "trainer_name": self.trainer_name,
            "resource_availability": {
                "ok": self.resource_availability.ok,
                "message": self.resource_availability.message,
            },
            "trainer_availability": {
                "ok": self.trainer_availability.ok,
                "message": self.trainer_availability.message,
            },
            "base_service_id": self.base_service_id,
            "training_service_id": self.training_service_id,
            "resource_id": self.resource_id,
            "duration_min": self.duration_min,
            "basket_unit": self.basket_unit,
            "basket_unit_label": self.basket_unit_label,
            "baskets": self.baskets,
            "basket_unit_price_kopecks": self.basket_unit_price_kopecks,
            "subtotal_kopecks": self.subtotal_kopecks,
            "membership_discount_kopecks": self.membership_discount_kopecks,
            "coupon_discount_kopecks": self.coupon_discount_kopecks,
            "discount_kopecks": self.discount_kopecks,
            "coupon_code": self.coupon_code,
            "coupon_label": self.coupon_label,
            "coupon_error": self.coupon_error,
            "membership_label": self.membership_label,
        }


# ─────────────────────────── core resolver ─────────────────────────────


_ACTIVE_STATUSES = (
    BookingStatus.HELD.value,
    BookingStatus.CONFIRMED.value,
    BookingStatus.CHECKED_IN.value,
    BookingStatus.COMPLETED.value,
)


def _fetch_service_by_sku(db: Session, sku: str) -> Optional[Service]:
    return db.execute(select(Service).where(Service.sku == sku)).scalar_one_or_none()


def _overlapping_bookings_on_resources(
    db: Session, resource_ids: list[int], starts_at: datetime, ends_at: datetime,
    exclude_id: Optional[int] = None,
) -> list[Booking]:
    if not resource_ids:
        return []
    q = select(Booking).where(
        Booking.resource_id.in_(resource_ids),
        Booking.status.in_(_ACTIVE_STATUSES),
        Booking.starts_at < ends_at,
        Booking.ends_at > starts_at,
    )
    if exclude_id:
        q = q.where(Booking.id != exclude_id)
    return list(db.execute(q).scalars())


def _overlapping_bookings_for_trainer(
    db: Session, trainer_id: int, starts_at: datetime, ends_at: datetime,
    exclude_id: Optional[int] = None,
) -> list[Booking]:
    q = select(Booking).where(
        Booking.instructor_id == trainer_id,
        Booking.status.in_(_ACTIVE_STATUSES),
        Booking.starts_at < ends_at,
        Booking.ends_at > starts_at,
    )
    if exclude_id:
        q = q.where(Booking.id != exclude_id)
    return list(db.execute(q).scalars())


def _pool_resource_ids(db: Session, pool_codes: set[str]) -> list[Resource]:
    rows = db.execute(
        select(Resource).where(Resource.code.in_(list(pool_codes)), Resource.active == True)  # noqa: E712
    ).scalars()
    return list(rows)


def resolve_scenario(db: Session, inp: ScenarioInput) -> ResolvedScenario:
    errors: list[str] = []
    warnings: list[str] = []

    cat_meta = CATEGORY_CATALOG.get(inp.category)
    if not cat_meta:
        return ResolvedScenario(
            ok=False, errors=[f"Неизвестная категория: {inp.category}"], warnings=[],
            base_price_kopecks=0, training_price_kopecks=0, total_kopecks=0,
            category_title="", category_short="", category_detail="",
            training_label="", trainer_name="",
            resource_availability=Availability(False, ""),
            trainer_availability=Availability(True, ""),
            base_service_id=None, training_service_id=None,
            resource_id=None, duration_min=60,
        )

    # ── basic input validation
    if inp.guests < 1:
        errors.append("Количество гостей должно быть не меньше 1.")

    if inp.ends_at <= inp.starts_at:
        errors.append("Время окончания должно быть позже времени начала.")

    # Opening hours: bookings must sit entirely within 08:00–22:00 local time
    # and not span across midnight.
    OPEN_MIN, CLOSE_MIN = 8 * 60, 22 * 60
    if inp.starts_at.date() != inp.ends_at.date():
        errors.append("Бронь должна быть в пределах одного дня.")
    else:
        start_min = inp.starts_at.hour * 60 + inp.starts_at.minute
        end_min = inp.ends_at.hour * 60 + inp.ends_at.minute
        if start_min < OPEN_MIN or end_min > CLOSE_MIN:
            errors.append("Клуб работает с 08:00 до 22:00 — бронь должна быть внутри этого окна.")

    # Hole 19,20 is single-slot regardless of guests count, but still guests ≥ 1.
    if inp.category == "hole_19_20" and inp.guests > 8:
        warnings.append("На лунке обычно играет до 4 гостей; уточните у гостя.")

    # Range capacity per-booking: limit to pool_capacity.
    if cat_meta["resource_pool"] == "range" and inp.guests > cat_meta["pool_capacity"]:
        errors.append(
            f"Максимум {cat_meta['pool_capacity']} гостей в одной брони Range."
        )

    # Training block validation
    training_label = ""
    training_sku = None
    training_price_kopecks = 0
    training_service_id = None
    trainer_name = ""

    if inp.has_training:
        if not inp.training_type:
            errors.append("Для тренировки выберите тип тренировки.")
        elif inp.training_type not in ("trial", "regular", "kids"):
            errors.append("Неизвестный тип тренировки.")
        else:
            key = (inp.training_type, inp.guests)
            if key not in TRAINING_MATRIX:
                errors.append(
                    f"Тренировочный тариф не задан для {inp.guests} "
                    f"{'ребёнка' if inp.training_type == 'kids' else 'гостей'}."
                    " Поддерживаются 1–4."
                )
            else:
                training_sku, training_price_kopecks = TRAINING_MATRIX[key]
                training_label = (
                    f"{TRAINING_TYPE_LABELS[inp.training_type]} "
                    f"({inp.guests} {'ребёнка' if inp.training_type == 'kids' else 'гостя'})"
                )

        if not inp.trainer_id:
            errors.append("Для тренировки обязательно выберите тренера.")
        else:
            trainer = db.get(Instructor, inp.trainer_id)
            if not trainer or not trainer.active:
                errors.append("Выбранный тренер недоступен.")
            else:
                trainer_name = trainer.name

    # ── resolve base service id (needed even on validation failure, for UI)
    base_service = _fetch_service_by_sku(db, cat_meta["sku"])
    base_service_id = base_service.id if base_service else None
    if base_service is None:
        errors.append(f"В каталоге отсутствует услуга {cat_meta['sku']}. Запустите seed.")

    # ── resource picking + capacity check
    resource_id: Optional[int] = None
    resource_availability = Availability(True, "")

    pool_codes = RANGE_RESOURCE_CODES if cat_meta["resource_pool"] == "range" else HOLE_19_20_CODES
    pool_resources = _pool_resource_ids(db, pool_codes)
    pool_ids = [r.id for r in pool_resources]
    if not pool_ids:
        errors.append("Площадка не найдена в каталоге ресурсов.")
        resource_availability = Availability(False, "Нет ресурсов для этой категории")
    else:
        overlap = _overlapping_bookings_on_resources(
            db, pool_ids, inp.starts_at, inp.ends_at, inp.exclude_booking_id
        )
        if cat_meta["resource_pool"] == "range":
            used_guests = sum(b.guests for b in overlap)
            remaining = cat_meta["pool_capacity"] - used_guests
            if inp.guests > remaining:
                msg = (
                    f"На Range свободно только {max(0, remaining)} мест из "
                    f"{cat_meta['pool_capacity']} в это время."
                )
                errors.append(msg)
                resource_availability = Availability(False, msg)
            else:
                resource_availability = Availability(
                    True,
                    f"На Range осталось {remaining - inp.guests} мест после этой брони (из 8)."
                )
                # pick the resource with smallest active guest load (simple balancing)
                load: dict[int, int] = {rid: 0 for rid in pool_ids}
                for b in overlap:
                    load[b.resource_id] = load.get(b.resource_id, 0) + b.guests
                resource_id = min(pool_ids, key=lambda rid: load[rid])
        else:
            # hole_19_20: any overlap blocks.
            if overlap:
                msg = "Лунка 19, 20 уже занята на выбранное время."
                errors.append(msg)
                resource_availability = Availability(False, msg)
            else:
                resource_availability = Availability(True, "Лунка 19, 20 свободна.")
                resource_id = pool_ids[0]

    # ── trainer availability
    trainer_availability = Availability(True, "")
    if inp.has_training and inp.trainer_id and trainer_name:
        t_overlap = _overlapping_bookings_for_trainer(
            db, inp.trainer_id, inp.starts_at, inp.ends_at, inp.exclude_booking_id
        )
        if t_overlap:
            msg = f"Тренер {trainer_name} уже занят в это время."
            errors.append(msg)
            trainer_availability = Availability(False, msg)
        else:
            trainer_availability = Availability(True, f"Тренер {trainer_name} свободен.")

    # ── resolve training service id
    if inp.has_training and training_sku:
        svc = _fetch_service_by_sku(db, training_sku)
        if svc:
            training_service_id = svc.id
        else:
            errors.append(f"В каталоге отсутствует тренировка {training_sku}. Запустите seed.")

    # Basket-unit pricing: currently only range_weekday_basket bills per basket.
    # per_guest pricing: weekend hour — each guest pays separately (unlimited balls).
    basket_unit = bool(cat_meta.get("basket_unit"))
    basket_unit_label = cat_meta.get("basket_unit_label", "")
    per_guest = bool(cat_meta.get("per_guest"))
    unit_price = cat_meta["base_price_kopecks"] if base_service else 0
    baskets = 1
    if basket_unit:
        baskets = max(1, int(inp.baskets or 1))
        if baskets > 20:
            errors.append("Слишком много корзин в одной брони (максимум 20).")
        base_price_kopecks = unit_price * baskets
    elif per_guest:
        # Weekend hour: charge per guest (balls unlimited).
        base_price_kopecks = unit_price * max(1, inp.guests)
    else:
        # business rule (§17): base is flat per booking, NOT × guests.
        base_price_kopecks = unit_price

    subtotal = base_price_kopecks + training_price_kopecks

    # ── membership / абонемент discount
    # Two independent perks on a plan (can stack):
    #   1. covers_training → трэйнер-часть = 0 (while max_trainings not exhausted)
    #   2. discount_percent → percentage off remaining subtotal
    membership_discount = 0
    membership_label = ""
    if inp.membership_id:
        m = db.get(Membership, inp.membership_id)
        if m and m.active and (not inp.customer_id or m.customer_id == inp.customer_id):
            plan = db.get(MembershipPlan, m.plan_id) if m else None
            labels: list[str] = []
            coverage = 0
            # Training coverage (абонемент): zero out the lesson part
            if (plan and plan.covers_training and inp.has_training
                    and training_price_kopecks > 0):
                cap = int(plan.max_trainings or 0)
                used = int(m.trainings_used or 0)
                if cap == 0 or used < cap:
                    coverage = training_price_kopecks
                    labels.append("тренировка покрыта")
                else:
                    warnings.append(
                        f"Абонемент «{plan.name}» исчерпан — осталось {max(0, cap - used)} тренировок."
                    )
            # Percentage discount on the uncovered remainder
            pct = int(plan.discount_percent or 0) if plan else 0
            pct_discount = 0
            if pct > 0:
                after_coverage = max(0, subtotal - coverage)
                pct_discount = after_coverage * pct // 100
                labels.append(f"−{pct}%")
            membership_discount = coverage + pct_discount
            if plan and labels:
                membership_label = f"{plan.name} ({', '.join(labels)})"
            elif plan:
                membership_label = plan.name
        elif m and inp.customer_id and m.customer_id != inp.customer_id:
            warnings.append("Абонемент не принадлежит выбранному клиенту — пропущен.")

    # ── coupon discount (percent or fixed, on subtotal − membership)
    coupon_discount = 0
    coupon_code_valid = ""
    coupon_label = ""
    coupon_error = ""
    code = (inp.coupon_code or "").strip()
    if code:
        from datetime import date as _date
        c = db.execute(select(Coupon).where(Coupon.code == code)).scalar_one_or_none()
        today = _date.today()
        after_mem = max(0, subtotal - membership_discount)
        if not c:
            coupon_error = "Промокод не найден"
        elif not c.active:
            coupon_error = "Промокод деактивирован"
        elif c.valid_from and today < c.valid_from:
            coupon_error = f"Активен с {c.valid_from}"
        elif c.valid_to and today > c.valid_to:
            coupon_error = f"Истёк {c.valid_to}"
        elif c.max_uses and c.used_count >= c.max_uses:
            coupon_error = "Исчерпан лимит использований"
        else:
            if c.kind == "percent":
                coupon_discount = after_mem * c.value // 100
                coupon_label = f"{c.code} (−{c.value}%)"
            else:  # fixed (value stored in rubles)
                coupon_discount = min(after_mem, c.value * 100)
                coupon_label = f"{c.code} (−{c.value} ₽)"
            coupon_code_valid = c.code

    discount = membership_discount + coupon_discount
    total = max(0, subtotal - discount)

    return ResolvedScenario(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        base_price_kopecks=base_price_kopecks,
        training_price_kopecks=training_price_kopecks,
        total_kopecks=total,
        category_title=cat_meta["title"],
        category_short=cat_meta["short"],
        category_detail=cat_meta["detail"],
        training_label=training_label,
        trainer_name=trainer_name,
        resource_availability=resource_availability,
        trainer_availability=trainer_availability,
        base_service_id=base_service_id,
        training_service_id=training_service_id,
        resource_id=resource_id,
        duration_min=cat_meta["duration_min"],
        basket_unit=basket_unit,
        basket_unit_label=basket_unit_label,
        baskets=baskets,
        basket_unit_price_kopecks=unit_price,
        subtotal_kopecks=subtotal,
        membership_discount_kopecks=membership_discount,
        coupon_discount_kopecks=coupon_discount,
        discount_kopecks=discount,
        coupon_code=coupon_code_valid,
        coupon_label=coupon_label,
        coupon_error=coupon_error,
        membership_label=membership_label,
    )


def categories_public() -> list[dict]:
    """List for the frontend tile picker."""
    return [
        {
            "code": code,
            "title": meta["title"],
            "short": meta["short"],
            "detail": meta["detail"],
            "base_price_kopecks": meta["base_price_kopecks"],
            "duration_min": meta["duration_min"],
            "pool_capacity": meta["pool_capacity"],
            "basket_unit": bool(meta.get("basket_unit")),
            "basket_unit_label": meta.get("basket_unit_label", ""),
            "per_guest": bool(meta.get("per_guest")),
        }
        for code, meta in CATEGORY_CATALOG.items()
    ]


def training_options_public() -> list[dict]:
    """List for the frontend training type picker with per-guest prices."""
    out = []
    for t in ("trial", "regular", "kids"):
        rows = [
            {"guests": g, "sku": sku, "price_kopecks": price}
            for (tt, g), (sku, price) in TRAINING_MATRIX.items()
            if tt == t
        ]
        rows.sort(key=lambda r: r["guests"])
        out.append({
            "type": t,
            "label": TRAINING_TYPE_LABELS[t],
            "prices": rows,
        })
    return out

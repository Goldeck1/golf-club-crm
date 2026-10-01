"""Rich dashboard analytics: heatmap, pace, revenue-by-category, utilization, RevPATT."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..db import get_db
from ..deps import get_current_user
from ..config import settings
from ..models import (
    Booking, Service, Resource, Customer, AuditLog, Zone, BookingItem,
    Membership, MembershipPlan,
)
from ..enums import BookingStatus, PaymentStatus
from ..scheduler import visible_resources

router = APIRouter(prefix="/analytics", tags=["analytics"])


class HeatmapCell(BaseModel):
    weekday: int
    hour: int
    count: int


class PaceDay(BaseModel):
    day: date
    count: int
    revenue_kopecks: int


class CategoryRevenue(BaseModel):
    category: str
    revenue_kopecks: int
    count: int


class UtilizationRow(BaseModel):
    resource_id: int
    name: str
    used_hours: float
    pct: float


class TopDay(BaseModel):
    day: date
    revenue_kopecks: int
    count: int


class AnalyticsOverview(BaseModel):
    today_count: int
    week_count: int
    month_count: int
    week_revenue_kopecks: int
    month_revenue_kopecks: int
    total_active: int
    no_show_week: int
    cancel_week: int
    clients_count: int
    resources_count: int
    revpatt_kopecks: int
    heatmap: List[HeatmapCell]
    heatmap_max: int
    pace: List[PaceDay]
    revenue_by_category: List[CategoryRevenue]
    utilization: List[UtilizationRow]
    top_days: List[TopDay]


@router.get("/overview", response_model=AnalyticsOverview)
def overview(user=Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    def count_since(since: date) -> int:
        return db.scalar(
            select(func.count()).select_from(Booking)
            .where(func.date(Booking.starts_at) >= since)
        ) or 0

    def paid_rev(since: date) -> int:
        return db.scalar(
            select(func.coalesce(func.sum(Booking.total_kopecks), 0))
            .where(
                func.date(Booking.starts_at) >= since,
                Booking.payment_status == PaymentStatus.PAID.value,
            )
        ) or 0

    def count_status(status: str, since: date) -> int:
        return db.scalar(
            select(func.count()).select_from(Booking)
            .where(
                func.date(Booking.starts_at) >= since,
                Booking.status == status,
            )
        ) or 0

    total_active = db.scalar(
        select(func.count()).select_from(Booking)
        .where(Booking.status.in_([BookingStatus.CONFIRMED.value, BookingStatus.CHECKED_IN.value]))
    ) or 0

    heatmap_rows = db.execute(
        select(Booking.starts_at).where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
        )
    ).scalars().all()
    grid: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for dt in heatmap_rows:
        grid[dt.weekday()][dt.hour] += 1
    heatmap: List[HeatmapCell] = []
    for wd, hours in grid.items():
        for h, c in hours.items():
            heatmap.append(HeatmapCell(weekday=wd, hour=h, count=c))
    heatmap_max = max((c.count for c in heatmap), default=1)

    pace_rows = db.execute(
        select(
            func.date(Booking.starts_at).label("d"),
            func.count().label("c"),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label("rev"),
        )
        .where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by("d").order_by("d")
    ).all()
    pace = [
        PaceDay(day=date.fromisoformat(str(r.d)), count=r.c, revenue_kopecks=r.rev)
        for r in pace_rows
    ]

    # Revenue by category
    cat_rows = db.execute(
        select(
            func.coalesce(Service.category, "без услуги").label("cat"),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label("rev"),
            func.count(Booking.id).label("cnt"),
        )
        .select_from(Booking)
        .outerjoin(Service, Service.id == Booking.service_id)
        .where(
            Booking.payment_status == PaymentStatus.PAID.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by("cat").order_by(func.sum(Booking.total_kopecks).desc())
    ).all()
    revenue_by_category = [
        CategoryRevenue(category=r.cat, revenue_kopecks=r.rev, count=r.cnt)
        for r in cat_rows
    ]

    top_rows = db.execute(
        select(
            func.date(Booking.starts_at).label("d"),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label("rev"),
            func.count(Booking.id).label("cnt"),
        )
        .where(
            Booking.payment_status == PaymentStatus.PAID.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by("d").order_by(func.sum(Booking.total_kopecks).desc()).limit(5)
    ).all()
    top_days = [
        TopDay(day=date.fromisoformat(str(r.d)), revenue_kopecks=r.rev, count=r.cnt)
        for r in top_rows
    ]

    # Utilization per resource
    used_hours: dict[int, float] = defaultdict(float)
    names: dict[int, str] = {}
    all_res = list(db.execute(
        select(Resource).where(Resource.active == True)  # noqa: E712
    ).scalars())
    for r in all_res:
        names[r.id] = r.name
        used_hours[r.id] = 0.0
    booked = list(db.execute(
        select(Booking).where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
            Booking.resource_id.isnot(None),
        )
    ).scalars())
    for b in booked:
        used_hours[b.resource_id] += (b.ends_at - b.starts_at).total_seconds() / 3600
    work_hours = settings.CLOSING_HOUR - settings.OPENING_HOUR
    available_per_resource = max(work_hours * 30, 1)
    utilization = sorted(
        [
            UtilizationRow(
                resource_id=rid,
                name=names[rid],
                used_hours=round(h, 1),
                pct=min(100.0, round(h * 100 / available_per_resource, 1)),
            )
            for rid, h in used_hours.items()
        ],
        key=lambda x: -x.used_hours,
    )[:10]

    resources_count = len(visible_resources(db))
    slots_per_hour = 60 // settings.SLOT_MINUTES
    total_slots_month = max(resources_count * work_hours * slots_per_hour * 30, 1)
    month_revenue = paid_rev(month_ago)
    revpatt_kopecks = month_revenue // total_slots_month

    clients_count = db.scalar(select(func.count()).select_from(Customer)) or 0

    return AnalyticsOverview(
        today_count=count_since(today),
        week_count=count_since(week_ago),
        month_count=count_since(month_ago),
        week_revenue_kopecks=paid_rev(week_ago),
        month_revenue_kopecks=month_revenue,
        total_active=total_active,
        no_show_week=count_status(BookingStatus.NO_SHOW.value, week_ago),
        cancel_week=count_status(BookingStatus.CANCELLED.value, week_ago),
        clients_count=clients_count,
        resources_count=resources_count,
        revpatt_kopecks=revpatt_kopecks,
        heatmap=heatmap,
        heatmap_max=heatmap_max,
        pace=pace,
        revenue_by_category=revenue_by_category,
        utilization=utilization,
        top_days=top_days,
    )


# ════════════════════════════════════════════════════════════════════════
# Business analytics — for club owner. Human-readable directions, zone
# load weighted by guests, and an explainable forecast.
# ════════════════════════════════════════════════════════════════════════


class DailyPoint(BaseModel):
    day: date
    revenue_kopecks: int
    bookings: int


class DirectionRow(BaseModel):
    code: str           # internal key (stable for UI)
    label: str          # human label
    revenue_kopecks: int
    bookings: int
    guests: int
    extra: str = ""     # optional detail ("всего 14 корзин")


class ZoneLoad(BaseModel):
    zone: str
    bookings: int
    guests: int
    hours: float


class ResourceLoad(BaseModel):
    resource_id: int
    name: str
    zone: str
    bookings: int
    guests: int
    hours: float


class ForecastDay(BaseModel):
    day: date
    revenue_kopecks: int
    weekday: int


class WeekdayLoad(BaseModel):
    weekday: int
    label: str
    bookings: int
    guests: int


class TopCustomer(BaseModel):
    customer_id: int
    name: str
    bookings: int
    guests: int
    top_zone: str
    revenue_kopecks: int


class BusinessSummary(BaseModel):
    # top cards
    revenue_today_kopecks: int
    revenue_7d_kopecks: int
    revenue_7d_prev_kopecks: int            # previous 7d — for delta
    revenue_30d_kopecks: int
    bookings_today: int
    bookings_7d: int
    guests_7d: int
    avg_check_7d_kopecks: int
    top_zone_name: str
    top_zone_guests: int
    top_direction_label: str
    top_direction_revenue_kopecks: int

    # main charts
    revenue_by_day_30d: list[DailyPoint]
    directions_30d: list[DirectionRow]
    zone_load_30d: list[ZoneLoad]
    resource_load_30d: list[ResourceLoad]
    heatmap: list[HeatmapCell]
    heatmap_max: int
    top_weekdays: list[WeekdayLoad]
    top_customers: list[TopCustomer]

    # forecast
    forecast_next_7d: list[ForecastDay]
    forecast_next_7d_total_kopecks: int
    forecast_next_30d_total_kopecks: int
    forecast_method: str                    # human-friendly one-liner

    # secondary
    no_show_week: int
    cancel_week: int
    revpatt_kopecks: int
    clients_count: int
    resources_count: int

    # Абонементы — продажи за период (учитываются в общем доходе клуба)
    subscriptions_sold_7d: int = 0
    subscriptions_revenue_7d_kopecks: int = 0
    subscriptions_sold_30d: int = 0
    subscriptions_revenue_30d_kopecks: int = 0
    subscriptions_active: int = 0
    # Топ абонементов по количеству продаж за 30 дней
    top_subscriptions_30d: list[dict] = []

    # Total revenue = booking revenue + subscription-sale revenue
    total_revenue_today_kopecks: int = 0
    total_revenue_7d_kopecks: int = 0
    total_revenue_30d_kopecks: int = 0

    # Новые клиенты — сколько гостей впервые зарегистрированы за период.
    new_customers_7d: int = 0
    new_customers_30d: int = 0


# Revenue is only recognised once the admin presses «Завершить» — while a booking
# is merely confirmed or checked-in, the money hasn't been earned yet.
_COUNTED_STATUSES = (BookingStatus.COMPLETED.value,)


def _training_label(sku: str | None) -> str | None:
    """Map a training service SKU to a human suffix."""
    if not sku:
        return None
    if sku.startswith("trial-lesson-"):
        return "пробная тренировка"
    if sku.startswith("kids-lesson-"):
        return "детская тренировка"
    if sku.startswith("lesson-"):
        return "обычная тренировка"
    return None


def _classify_direction(
    base_service: Service | None,
    training_sku: str | None,
) -> tuple[str, str]:
    """Return (stable code, human label) from base service + optional training SKU."""
    base_sku = base_service.sku if base_service else None
    base_cat = base_service.category if base_service else None
    t_suffix = _training_label(training_sku)

    # New scenario-based bookings: base service carries the venue
    if base_sku == "driving-basket-40-weekday":
        if t_suffix:
            return f"range_weekday_basket::{t_suffix}", f"Range · будни · корзины + {t_suffix}"
        return "range_weekday_basket", "Range · будни · корзины"

    if base_sku == "driving-1h-weekend":
        if t_suffix:
            return f"range_weekend_hour::{t_suffix}", f"Range · выходные · 1 час + {t_suffix}"
        return "range_weekend_hour", "Range · выходные · 1 час"

    if base_sku == "academic-holes-19-20" or base_cat == "academic_holes":
        if t_suffix:
            return f"hole_19_20::{t_suffix}", f"Лунка 19,20 + {t_suffix}"
        return "hole_19_20", "Лунка 19,20"

    # driving_range without a specific SKU (shouldn't happen in new data)
    if base_cat == "driving_range":
        if t_suffix:
            return f"range_generic::{t_suffix}", f"Range + {t_suffix}"
        return "range_generic", "Range"

    # Legacy bookings (old demo) where the lesson/trial/kids service was the only service.
    # Tag as "архив" so owner understands why they look different.
    if base_cat == "lesson_trial":
        return "legacy_trial", "Пробная тренировка (архив)"
    if base_cat == "lesson":
        return "legacy_regular", "Обычная тренировка (архив)"
    if base_cat == "lesson_kids":
        return "legacy_kids", "Детская тренировка (архив)"
    if base_cat == "simulator":
        return "simulator", "Симулятор"
    if base_cat == "billiard":
        return "billiard", "Бильярд"
    return "other", "Прочее"


@router.get("/business", response_model=BusinessSummary)
def business(user=Depends(get_current_user), db: Session = Depends(get_db)):
    today = date.today()
    d7_ago = today - timedelta(days=6)               # inclusive 7 days
    d14_ago = today - timedelta(days=13)
    d30_ago = today - timedelta(days=29)
    d28_ago_forecast = today - timedelta(days=27)    # rolling 4 weeks baseline

    # Revenue attributes money to the day the session was scheduled (starts_at)
    # — deliberately, so "завтра завершённая" бронь всё равно считается завтра.
    # Учёт всё ещё требует статус COMPLETED (деньги признаются только после
    # «Завершить»), но дата привязана к сессии, не к моменту нажатия.
    def rev_between(d_from: date, d_to: date) -> int:
        return db.scalar(
            select(func.coalesce(func.sum(Booking.total_kopecks), 0))
            .where(
                func.date(Booking.starts_at) >= d_from,
                func.date(Booking.starts_at) <= d_to,
                Booking.status.in_(_COUNTED_STATUSES),
            )
        ) or 0

    def count_between(d_from: date, d_to: date) -> int:
        return db.scalar(
            select(func.count()).select_from(Booking)
            .where(
                func.date(Booking.starts_at) >= d_from,
                func.date(Booking.starts_at) <= d_to,
                Booking.status.in_(_COUNTED_STATUSES),
            )
        ) or 0

    def guests_between(d_from: date, d_to: date) -> int:
        return db.scalar(
            select(func.coalesce(func.sum(Booking.guests), 0))
            .where(
                func.date(Booking.starts_at) >= d_from,
                func.date(Booking.starts_at) <= d_to,
                Booking.status.in_(_COUNTED_STATUSES),
            )
        ) or 0

    revenue_today = rev_between(today, today)
    revenue_7d = rev_between(d7_ago, today)
    revenue_7d_prev = rev_between(d14_ago, d7_ago - timedelta(days=1))
    revenue_30d = rev_between(d30_ago, today)
    bookings_today = count_between(today, today)
    bookings_7d = count_between(d7_ago, today)
    guests_7d = guests_between(d7_ago, today)
    avg_check_7d = revenue_7d // bookings_7d if bookings_7d else 0

    # ── revenue_by_day 30d — дата по starts_at (день сессии)
    rev_day_rows = db.execute(
        select(
            func.date(Booking.starts_at).label("d"),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label("rev"),
            func.count(Booking.id).label("cnt"),
        )
        .where(
            func.date(Booking.starts_at) >= d30_ago,
            func.date(Booking.starts_at) <= today,
            Booking.status.in_(_COUNTED_STATUSES),
        )
        .group_by("d")
    ).all()
    by_day: dict[date, tuple[int, int]] = {}
    for r in rev_day_rows:
        d = r.d if isinstance(r.d, date) else date.fromisoformat(str(r.d))
        by_day[d] = (int(r.rev), int(r.cnt))
    revenue_by_day: list[DailyPoint] = []
    cur = d30_ago
    while cur <= today:
        rev, cnt = by_day.get(cur, (0, 0))
        revenue_by_day.append(DailyPoint(day=cur, revenue_kopecks=rev, bookings=cnt))
        cur += timedelta(days=1)

    # ── directions (business-named, based on base service + training BookingItem)
    bookings_30d = list(db.execute(
        select(Booking, Service)
        .outerjoin(Service, Service.id == Booking.service_id)
        .where(
            func.date(Booking.starts_at) >= d30_ago,
            func.date(Booking.starts_at) <= today,
            Booking.status.in_(_COUNTED_STATUSES),
        )
    ).all())
    booking_ids = [b.id for b, _ in bookings_30d]

    # Collect booking items with their services — we need SKU to detect training and
    # basket quantity. Single query, in-memory grouping.
    items_rows = []
    if booking_ids:
        items_rows = list(db.execute(
            select(BookingItem, Service)
            .outerjoin(Service, Service.id == BookingItem.service_id)
            .where(BookingItem.booking_id.in_(booking_ids))
        ).all())
    items_by_booking: dict[int, list[tuple[BookingItem, Service | None]]] = {}
    for item, svc in items_rows:
        items_by_booking.setdefault(item.booking_id, []).append((item, svc))

    TRAINING_PREFIXES = ("lesson-", "trial-lesson-", "kids-lesson-")

    dir_acc: dict[str, dict] = {}
    total_baskets_weekday = 0
    for b, base_svc in bookings_30d:
        its = items_by_booking.get(b.id, [])
        training_sku: str | None = None
        basket_qty = 0
        for item, svc in its:
            sku = svc.sku if svc else None
            if sku and sku.startswith(TRAINING_PREFIXES):
                training_sku = sku
            if sku == "driving-basket-40-weekday":
                basket_qty += int(item.quantity or 1)
        # Fallback: legacy bookings may not have a training item, but an instructor_id
        # is set. In that case we still want to mark them as "+ тренировка" with
        # a generic label.
        if not training_sku and b.instructor_id and base_svc and base_svc.category in ("driving_range", "academic_holes"):
            training_sku = "lesson-legacy"

        code, label = _classify_direction(base_svc, training_sku)
        rec = dir_acc.setdefault(code, {
            "label": label, "rev": 0, "cnt": 0, "guests": 0, "baskets": 0,
        })
        rec["rev"] += int(b.total_kopecks or 0)
        rec["cnt"] += 1
        rec["guests"] += int(b.guests or 0)
        if code.startswith("range_weekday_basket"):
            rec["baskets"] += basket_qty or 1
            total_baskets_weekday += basket_qty or 1

    directions = sorted(
        [
            DirectionRow(
                code=code,
                label=rec["label"],
                revenue_kopecks=rec["rev"],
                bookings=rec["cnt"],
                guests=rec["guests"],
                extra=(f"всего {rec['baskets']} корзин" if rec.get("baskets") else ""),
            )
            for code, rec in dir_acc.items()
        ],
        key=lambda r: -r.revenue_kopecks,
    )

    # ── resource & zone load (weighted by guests)
    zone_map: dict[int, str] = {
        z.id: z.name
        for z in db.execute(select(Zone)).scalars()
    }
    resources_all = list(db.execute(select(Resource)).scalars())
    res_meta = {r.id: r for r in resources_all}

    rload: dict[int, dict] = {}
    zload: dict[str, dict] = {}
    for b, svc in bookings_30d:
        if not b.resource_id:
            continue
        r = res_meta.get(b.resource_id)
        if not r:
            continue
        zone_name = zone_map.get(r.zone_id, "—")
        hours = max(0.0, (b.ends_at - b.starts_at).total_seconds() / 3600.0)
        guests = int(b.guests or 0)

        rec = rload.setdefault(r.id, {
            "resource_id": r.id, "name": r.name, "zone": zone_name,
            "bookings": 0, "guests": 0, "hours": 0.0,
        })
        rec["bookings"] += 1
        rec["guests"] += guests
        rec["hours"] += hours

        zrec = zload.setdefault(zone_name, {"bookings": 0, "guests": 0, "hours": 0.0})
        zrec["bookings"] += 1
        zrec["guests"] += guests
        zrec["hours"] += hours

    resource_load = sorted(
        [ResourceLoad(**{**v, "hours": round(v["hours"], 1)}) for v in rload.values()],
        key=lambda r: -r.guests if r.guests else -r.bookings,
    )
    zone_load = sorted(
        [
            ZoneLoad(zone=z, bookings=v["bookings"], guests=v["guests"], hours=round(v["hours"], 1))
            for z, v in zload.items()
        ],
        key=lambda z: -z.guests if z.guests else -z.bookings,
    )
    top_zone_name = zone_load[0].zone if zone_load else "—"
    top_zone_guests = zone_load[0].guests if zone_load else 0
    top_direction_label = directions[0].label if directions else "—"
    top_direction_rev = directions[0].revenue_kopecks if directions else 0

    # ── heatmap (weekday × hour)
    heat_rows = db.execute(
        select(Booking.starts_at)
        .where(
            Booking.status.in_(_COUNTED_STATUSES),
            func.date(Booking.starts_at) >= d30_ago,
        )
    ).scalars().all()
    grid: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for dt in heat_rows:
        grid[dt.weekday()][dt.hour] += 1
    heatmap: list[HeatmapCell] = []
    for wd, hours in grid.items():
        for h, c in hours.items():
            heatmap.append(HeatmapCell(weekday=wd, hour=h, count=c))
    heatmap_max = max((c.count for c in heatmap), default=1)

    # ── top weekdays (by bookings + guests)
    weekday_names = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
    wd_acc: dict[int, dict] = {i: {"bookings": 0, "guests": 0} for i in range(7)}
    for b, _ in bookings_30d:
        wd = b.starts_at.weekday()
        wd_acc[wd]["bookings"] += 1
        wd_acc[wd]["guests"] += int(b.guests or 0)
    top_weekdays = sorted(
        [
            WeekdayLoad(
                weekday=wd, label=weekday_names[wd],
                bookings=rec["bookings"], guests=rec["guests"],
            )
            for wd, rec in wd_acc.items() if rec["bookings"] > 0
        ],
        key=lambda r: (-r.guests, -r.bookings),
    )

    # ── top customers (most active players)
    cust_acc: dict[int, dict] = {}
    for b, _ in bookings_30d:
        if not b.customer_id:
            continue
        rec = cust_acc.setdefault(b.customer_id, {
            "bookings": 0, "guests": 0, "revenue": 0, "zones": defaultdict(int),
        })
        rec["bookings"] += 1
        rec["guests"] += int(b.guests or 0)
        rec["revenue"] += int(b.total_kopecks or 0)
        if b.resource_id:
            r = res_meta.get(b.resource_id)
            if r:
                rec["zones"][zone_map.get(r.zone_id, "—")] += int(b.guests or 1)

    customer_ids = list(cust_acc.keys())
    customer_names: dict[int, str] = {}
    if customer_ids:
        for c in db.execute(select(Customer).where(Customer.id.in_(customer_ids))).scalars():
            customer_names[c.id] = c.name
    top_customers = sorted(
        [
            TopCustomer(
                customer_id=cid,
                name=customer_names.get(cid, f"Гость #{cid}"),
                bookings=rec["bookings"],
                guests=rec["guests"],
                revenue_kopecks=rec["revenue"],
                top_zone=max(rec["zones"].items(), key=lambda kv: kv[1])[0] if rec["zones"] else "—",
            )
            for cid, rec in cust_acc.items()
        ],
        key=lambda r: (-r.bookings, -r.guests),
    )[:8]

    # ── forecast: same-weekday average over last 28 days
    # Build per-weekday avg revenue from last 28 completed days (today-28 .. today)
    rev_by_weekday: dict[int, list[int]] = defaultdict(list)
    baseline_cur = today - timedelta(days=28)
    baseline_end = today - timedelta(days=1)  # use completed days only
    rows28 = db.execute(
        select(
            func.date(Booking.starts_at).label("d"),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label("rev"),
        )
        .where(
            func.date(Booking.starts_at) >= baseline_cur,
            func.date(Booking.starts_at) <= baseline_end,
            Booking.status.in_(_COUNTED_STATUSES),
        )
        .group_by("d")
    ).all()
    rev_by_date: dict[date, int] = {}
    for r in rows28:
        d = r.d if isinstance(r.d, date) else date.fromisoformat(str(r.d))
        rev_by_date[d] = int(r.rev)
    cur = baseline_cur
    while cur <= baseline_end:
        rev_by_weekday[cur.weekday()].append(rev_by_date.get(cur, 0))
        cur += timedelta(days=1)
    weekday_avg: dict[int, int] = {
        wd: int(sum(v) / len(v)) if v else 0 for wd, v in rev_by_weekday.items()
    }

    forecast_days: list[ForecastDay] = []
    total_next7 = 0
    for i in range(1, 8):
        d = today + timedelta(days=i)
        est = weekday_avg.get(d.weekday(), 0)
        forecast_days.append(ForecastDay(day=d, revenue_kopecks=est, weekday=d.weekday()))
        total_next7 += est

    # 30-day forecast: daily average × 30
    total_28 = sum(sum(v) for v in rev_by_weekday.values())
    daily_avg = total_28 // 28 if total_28 else 0
    total_next30 = daily_avg * 30

    forecast_method = (
        "Основано на средней выручке за последние 4 таких же дня недели (28 дней)."
    )

    # ── secondary
    no_show_week = db.scalar(
        select(func.count()).select_from(Booking).where(
            func.date(Booking.starts_at) >= d7_ago,
            Booking.status == BookingStatus.NO_SHOW.value,
        )
    ) or 0
    cancel_week = db.scalar(
        select(func.count()).select_from(Booking).where(
            func.date(Booking.starts_at) >= d7_ago,
            Booking.status == BookingStatus.CANCELLED.value,
        )
    ) or 0

    resources_count = len(visible_resources(db))
    work_hours = settings.CLOSING_HOUR - settings.OPENING_HOUR
    slots_per_hour = 60 // settings.SLOT_MINUTES
    total_slots_month = max(resources_count * work_hours * slots_per_hour * 30, 1)
    revpatt = revenue_30d // total_slots_month
    clients_count = db.scalar(select(func.count()).select_from(Customer)) or 0

    # ── Абонементы: продажи по starts_on и активные (ends_on >= today)
    def sub_stats(d_from: date, d_to: date) -> tuple[int, int]:
        rows = db.execute(
            select(MembershipPlan.price_kopecks)
            .select_from(Membership)
            .join(MembershipPlan, MembershipPlan.id == Membership.plan_id)
            .where(
                Membership.starts_on >= d_from,
                Membership.starts_on <= d_to,
            )
        ).all()
        return len(rows), int(sum(int(r[0] or 0) for r in rows))

    subs_today_cnt, subs_today_rev = sub_stats(today, today)
    subs_7_cnt, subs_7_rev = sub_stats(d7_ago, today)
    subs_30_cnt, subs_30_rev = sub_stats(d30_ago, today)
    subs_active = db.scalar(
        select(func.count()).select_from(Membership)
        .where(Membership.active == True, Membership.ends_on >= today)  # noqa: E712
    ) or 0

    # Top abonement purchases over 30d — grouped by plan.
    top_subs_rows = db.execute(
        select(
            MembershipPlan.id,
            MembershipPlan.name,
            func.count(Membership.id).label("cnt"),
            func.coalesce(func.sum(MembershipPlan.price_kopecks), 0).label("rev"),
        )
        .select_from(Membership)
        .join(MembershipPlan, MembershipPlan.id == Membership.plan_id)
        .where(
            Membership.starts_on >= d30_ago,
            Membership.starts_on <= today,
        )
        .group_by(MembershipPlan.id, MembershipPlan.name)
        .order_by(func.count(Membership.id).desc())
    ).all()
    top_subscriptions_30d = [
        {
            "plan_id": int(r[0]),
            "plan_name": r[1],
            "count": int(r[2]),
            "revenue_kopecks": int(r[3]),
        }
        for r in top_subs_rows
    ]

    # ── Новые клиенты за периоды (по created_at)
    def new_customers_between(d_from: date, d_to: date) -> int:
        return db.scalar(
            select(func.count()).select_from(Customer).where(
                func.date(Customer.created_at) >= d_from,
                func.date(Customer.created_at) <= d_to,
            )
        ) or 0

    new_customers_7d = new_customers_between(d7_ago, today)
    new_customers_30d = new_customers_between(d30_ago, today)

    return BusinessSummary(
        revenue_today_kopecks=revenue_today,
        revenue_7d_kopecks=revenue_7d,
        revenue_7d_prev_kopecks=revenue_7d_prev,
        revenue_30d_kopecks=revenue_30d,
        bookings_today=bookings_today,
        bookings_7d=bookings_7d,
        guests_7d=guests_7d,
        avg_check_7d_kopecks=avg_check_7d,
        top_zone_name=top_zone_name,
        top_zone_guests=top_zone_guests,
        top_direction_label=top_direction_label,
        top_direction_revenue_kopecks=top_direction_rev,
        revenue_by_day_30d=revenue_by_day,
        directions_30d=directions,
        zone_load_30d=zone_load,
        resource_load_30d=resource_load[:10],
        heatmap=heatmap,
        heatmap_max=heatmap_max,
        top_weekdays=top_weekdays,
        top_customers=top_customers,
        forecast_next_7d=forecast_days,
        forecast_next_7d_total_kopecks=total_next7,
        forecast_next_30d_total_kopecks=total_next30,
        forecast_method=forecast_method,
        no_show_week=int(no_show_week),
        cancel_week=int(cancel_week),
        revpatt_kopecks=revpatt,
        clients_count=int(clients_count),
        resources_count=int(resources_count),
        subscriptions_sold_7d=subs_7_cnt,
        subscriptions_revenue_7d_kopecks=subs_7_rev,
        subscriptions_sold_30d=subs_30_cnt,
        subscriptions_revenue_30d_kopecks=subs_30_rev,
        subscriptions_active=int(subs_active),
        top_subscriptions_30d=top_subscriptions_30d,
        total_revenue_today_kopecks=revenue_today + subs_today_rev,
        total_revenue_7d_kopecks=revenue_7d + subs_7_rev,
        total_revenue_30d_kopecks=revenue_30d + subs_30_rev,
        new_customers_7d=int(new_customers_7d),
        new_customers_30d=int(new_customers_30d),
    )

from datetime import datetime, date, timedelta
from collections import defaultdict
from flask import Blueprint, render_template
from flask_login import login_required
from sqlalchemy import select, func

from ..db import get_session
from ..domain import (
    Booking, BookingStatus, PaymentStatus, Customer, Resource, Service, AuditLog,
)
from ..config import Config
from ..services.scheduler import current_season, visible_resources

bp = Blueprint('dashboard', __name__)


@bp.route('/')
@login_required
def index():
    s = get_session()
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    def count(since):
        return s.execute(
            select(func.count()).select_from(Booking)
            .where(func.date(Booking.starts_at) >= since)
        ).scalar() or 0

    def paid_revenue(since):
        return s.execute(
            select(func.coalesce(func.sum(Booking.total_kopecks), 0))
            .where(
                func.date(Booking.starts_at) >= since,
                Booking.payment_status == PaymentStatus.PAID.value,
            )
        ).scalar() or 0

    def count_status(status, since):
        return s.execute(
            select(func.count()).select_from(Booking)
            .where(
                func.date(Booking.starts_at) >= since,
                Booking.status == status,
            )
        ).scalar() or 0

    total_active = s.execute(
        select(func.count()).select_from(Booking)
        .where(Booking.status.in_([
            BookingStatus.CONFIRMED.value,
            BookingStatus.CHECKED_IN.value,
        ]))
    ).scalar() or 0

    no_show_week = count_status(BookingStatus.NO_SHOW.value, week_ago)
    cancel_week = count_status(BookingStatus.CANCELLED.value, week_ago)

    # upcoming today
    upcoming_today = s.execute(
        select(Booking).where(
            func.date(Booking.starts_at) == today,
            Booking.status.in_([
                BookingStatus.CONFIRMED.value,
                BookingStatus.CHECKED_IN.value,
            ]),
        ).order_by(Booking.starts_at)
    ).scalars().all()

    clients_count = s.execute(select(func.count()).select_from(Customer)).scalar() or 0

    recent_audit = s.execute(
        select(AuditLog).order_by(AuditLog.at.desc()).limit(8)
    ).scalars().all()

    # ─── Тепловая карта загрузки (день недели × час) за 30 дней ──
    heatmap = defaultdict(lambda: defaultdict(int))
    heatmap_rows = s.execute(
        select(Booking.starts_at).where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
        )
    ).scalars().all()
    for dt in heatmap_rows:
        heatmap[dt.weekday()][dt.hour] += 1
    heatmap_max = max(
        (v for w in heatmap.values() for v in w.values()),
        default=1,
    )

    # ─── Booking pace: каждый день последних 30 дней ──
    pace_raw = s.execute(
        select(
            func.date(Booking.starts_at).label('d'),
            func.count().label('c'),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label('rev'),
        )
        .where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by('d')
        .order_by('d')
    ).all()
    pace_labels = [r.d for r in pace_raw]
    pace_values = [r.c for r in pace_raw]

    # ─── RevPATT: Revenue per Available Tee Time ──
    # Формула: total revenue / (resources * working hours * slots_per_hour * days)
    resources_count = len(visible_resources())
    work_hours = Config.CLOSING_HOUR - Config.OPENING_HOUR
    slots_per_hour = 60 // Config.SLOT_MINUTES
    month_revenue = paid_revenue(month_ago)
    total_slots_month = resources_count * work_hours * slots_per_hour * 30 or 1
    revpatt_kopecks = month_revenue // total_slots_month

    # ─── Разложение выручки по категориям (stacked) ──
    revenue_by_cat = s.execute(
        select(
            func.coalesce(Service.category, 'без услуги').label('cat'),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label('rev'),
            func.count(Booking.id).label('cnt')
        )
        .select_from(Booking)
        .outerjoin(Service, Service.id == Booking.service_id)
        .where(
            Booking.payment_status == PaymentStatus.PAID.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by('cat')
        .order_by(func.sum(Booking.total_kopecks).desc())
    ).all()
    cat_labels = [r.cat for r in revenue_by_cat]
    cat_values = [r.rev // 100 for r in revenue_by_cat]
    cat_counts = [r.cnt for r in revenue_by_cat]

    # ─── Топ-5 дней по выручке ──
    top_days = s.execute(
        select(
            func.date(Booking.starts_at).label('d'),
            func.coalesce(func.sum(Booking.total_kopecks), 0).label('rev'),
            func.count(Booking.id).label('cnt'),
        )
        .where(
            Booking.payment_status == PaymentStatus.PAID.value,
            func.date(Booking.starts_at) >= month_ago,
        )
        .group_by('d').order_by(func.sum(Booking.total_kopecks).desc()).limit(5)
    ).all()

    # ─── Утилизация по ресурсам (30 дней) — считаем часы в Python из starts/ends ──
    util_hours = defaultdict(float)
    util_names = {}
    all_res = s.execute(select(Resource).where(Resource.active == True)).scalars().all()
    for r in all_res:
        util_names[r.id] = r.name
        util_hours[r.id] = 0.0
    booked = s.execute(
        select(Booking).where(
            Booking.status != BookingStatus.CANCELLED.value,
            func.date(Booking.starts_at) >= month_ago,
            Booking.resource_id.isnot(None),
        )
    ).scalars().all()
    for b in booked:
        util_hours[b.resource_id] += (b.ends_at - b.starts_at).total_seconds() / 3600
    available_hours_per_resource = work_hours * 30
    utilization = sorted(
        [
            {'name': util_names[rid], 'used': round(h, 1),
             'pct': min(100, round(h * 100 / max(available_hours_per_resource, 1), 1))}
            for rid, h in util_hours.items()
        ],
        key=lambda x: -x['used'],
    )[:10]

    return render_template('dashboard/index.html',
                           today_count=count(today),
                           week_count=count(week_ago),
                           month_count=count(month_ago),
                           week_revenue=paid_revenue(week_ago),
                           month_revenue=month_revenue,
                           total_active=total_active,
                           no_show_week=no_show_week,
                           cancel_week=cancel_week,
                           clients_count=clients_count,
                           upcoming_today=upcoming_today,
                           recent_audit=recent_audit,
                           resources_count=resources_count,
                           season=current_season(),
                           # новые виджеты
                           heatmap=heatmap,
                           heatmap_max=heatmap_max,
                           pace_labels=pace_labels,
                           pace_values=pace_values,
                           revpatt_kopecks=revpatt_kopecks,
                           cat_labels=cat_labels,
                           cat_values=cat_values,
                           cat_counts=cat_counts,
                           top_days=top_days,
                           utilization=utilization,
                           opening_hour=Config.OPENING_HOUR,
                           closing_hour=Config.CLOSING_HOUR)

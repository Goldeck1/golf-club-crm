from datetime import datetime, timedelta, date
from collections import defaultdict
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required, current_user
from sqlalchemy import select, func

from ..db import get_session
from ..domain import (
    Booking, BookingStatus, PaymentStatus, Customer, Resource, Service, Instructor,
    AuditLog,
)
from ..services import booking_service
from ..services.auth import manager_required
from ..services.scheduler import visible_resources, current_season

bp = Blueprint('bookings', __name__)


# ─── Список и поиск ────────────────────────────────────────────────

@bp.route('/bookings')
@login_required
def index():
    s = get_session()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    payment = request.args.get('payment', '').strip()
    status = request.args.get('status', '').strip()

    q = select(Booking).order_by(Booking.starts_at.desc())
    if date_from:
        q = q.where(func.date(Booking.starts_at) >= date_from)
    if date_to:
        q = q.where(func.date(Booking.starts_at) <= date_to)
    if payment in ('paid', 'unpaid'):
        if payment == 'paid':
            q = q.where(Booking.payment_status == PaymentStatus.PAID.value)
        else:
            q = q.where(Booking.payment_status != PaymentStatus.PAID.value)
    if status:
        q = q.where(Booking.status == status)

    bookings = s.execute(q.limit(500)).scalars().all()
    return render_template('bookings/index.html',
                           bookings=bookings,
                           date_from=date_from, date_to=date_to,
                           payment=payment, status=status,
                           statuses=[e.value for e in BookingStatus])


# ─── Форма создания ────────────────────────────────────────────────

@bp.route('/bookings/new', methods=['GET', 'POST'])
@manager_required
def new():
    s = get_session()
    season = current_season()

    if request.method == 'POST':
        try:
            starts_at = datetime.fromisoformat(
                f"{request.form['date']}T{request.form['slot']}"
            )
        except (KeyError, ValueError):
            flash('Укажите корректную дату и время', 'error')
            return redirect(url_for('bookings.new'))

        duration_h = float(request.form.get('duration') or 1)
        ends_at = starts_at + timedelta(minutes=int(duration_h * 60))

        # Клиент: либо выбран, либо создаём
        client_id = request.form.get('client_id') or None
        if not client_id:
            new_name = request.form.get('new_client_name', '').strip()
            new_phone = request.form.get('new_client_phone', '').strip()
            if new_name:
                c = Customer(name=new_name, phone=new_phone)
                s.add(c)
                s.flush()
                client_id = c.id

        try:
            booking = booking_service.create_booking(
                resource_id=int(request.form['resource_id']) if request.form.get('resource_id') else None,
                service_id=int(request.form['service_id']) if request.form.get('service_id') else None,
                customer_id=int(client_id) if client_id else None,
                instructor_id=int(request.form['instructor_id']) if request.form.get('instructor_id') else None,
                starts_at=starts_at,
                ends_at=ends_at,
                guests=int(request.form.get('guests') or 1),
                with_guest=bool(request.form.get('with_guest')),
                price_kopecks=int(request.form.get('price_rub') or 0) * 100,
                comment=request.form.get('comment', '').strip(),
            )
        except booking_service.SchedulerConflict as e:
            flash(f'Конфликт: ресурс занят ({len(e.conflicts)} пересечений)', 'error')
            return redirect(url_for('bookings.new'))

        flash(f'Бронь #{booking.id} создана', 'success')
        return redirect(url_for('calendar.index', date=booking.starts_at.date().isoformat()))

    # GET
    services = s.execute(
        select(Service).where(
            Service.active == True,
            Service.season.in_(['all_year', season]),
        ).order_by(Service.category, Service.base_price_kopecks)
    ).scalars().all()
    by_cat = defaultdict(list)
    for sv in services:
        by_cat[sv.category].append(sv)

    clients = s.execute(select(Customer).order_by(Customer.name)).scalars().all()
    instructors = s.execute(
        select(Instructor).where(Instructor.active == True).order_by(Instructor.name)
    ).scalars().all()
    resources = visible_resources()
    resources_by_zone = defaultdict(list)
    for r in resources:
        resources_by_zone[r.zone.name].append(r)

    return render_template('bookings/form.html',
                           services_by_category=by_cat,
                           clients=clients, instructors=instructors,
                           resources_by_zone=resources_by_zone,
                           today=date.today().isoformat(),
                           season=season)


# ─── Drawer: детали по id (HTMX) ───────────────────────────────────

@bp.route('/bookings/<int:bid>/drawer')
@login_required
def drawer(bid):
    s = get_session()
    booking = s.get(Booking, bid)
    if not booking:
        abort(404)
    audit_entries = s.execute(
        select(AuditLog).where(AuditLog.entity == 'booking', AuditLog.entity_id == bid)
        .order_by(AuditLog.at.desc()).limit(20)
    ).scalars().all()
    return render_template('bookings/_drawer.html',
                           b=booking, audit_entries=audit_entries)


# ─── Переходы статусов (HTMX POST) ─────────────────────────────────

def _get_or_404(bid):
    b = get_session().get(Booking, bid)
    if not b:
        abort(404)
    return b


@bp.route('/bookings/<int:bid>/check-in', methods=['POST'])
@login_required
def check_in(bid):
    try:
        booking_service.check_in(_get_or_404(bid))
        flash('Check-in', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return _after_action_redirect(bid)


@bp.route('/bookings/<int:bid>/complete', methods=['POST'])
@login_required
def complete(bid):
    try:
        booking_service.complete(_get_or_404(bid))
        flash('Бронь завершена', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return _after_action_redirect(bid)


@bp.route('/bookings/<int:bid>/cancel', methods=['POST'])
@manager_required
def cancel(bid):
    reason = request.form.get('reason', '').strip()
    try:
        booking_service.cancel(_get_or_404(bid), reason=reason)
        flash('Бронь отменена', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return _after_action_redirect(bid)


@bp.route('/bookings/<int:bid>/no-show', methods=['POST'])
@manager_required
def no_show(bid):
    try:
        booking_service.mark_no_show(_get_or_404(bid))
        flash('Отмечено как No-show', 'success')
    except ValueError as e:
        flash(str(e), 'error')
    return _after_action_redirect(bid)


@bp.route('/bookings/<int:bid>/pay', methods=['POST'])
@login_required
def pay(bid):
    method = request.form.get('method', 'cash')
    booking_service.mark_paid(_get_or_404(bid), method=method)
    flash('Отмечено как оплаченное', 'success')
    return _after_action_redirect(bid)


def _after_action_redirect(bid):
    if request.headers.get('HX-Request'):
        s = get_session()
        b = s.get(Booking, bid)
        audit_entries = s.execute(
            select(AuditLog).where(AuditLog.entity == 'booking', AuditLog.entity_id == bid)
            .order_by(AuditLog.at.desc()).limit(20)
        ).scalars().all()
        return render_template('bookings/_drawer.html', b=b, audit_entries=audit_entries)
    return redirect(request.referrer or url_for('calendar.index'))

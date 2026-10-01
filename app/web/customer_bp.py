from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required
from sqlalchemy import select, func, or_

from ..db import get_session
from ..domain import Customer, Booking, PaymentStatus

bp = Blueprint('customers', __name__)


@bp.route('/clients')
@login_required
def index():
    s = get_session()
    q = request.args.get('q', '').strip()
    query = select(Customer).order_by(Customer.name)
    if q:
        like = f'%{q}%'
        query = query.where(or_(
            Customer.name.ilike(like),
            Customer.phone.ilike(like),
            Customer.email.ilike(like),
        ))
    customers = s.execute(query).scalars().all()

    # stats per customer
    stats = {}
    for c in customers:
        n = s.execute(
            select(func.count()).select_from(Booking).where(Booking.customer_id == c.id)
        ).scalar() or 0
        paid = s.execute(
            select(func.coalesce(func.sum(Booking.total_kopecks), 0))
            .where(Booking.customer_id == c.id, Booking.payment_status == PaymentStatus.PAID.value)
        ).scalar() or 0
        stats[c.id] = {'count': n, 'paid': paid}

    return render_template('customers/index.html', customers=customers, q=q, stats=stats)


@bp.route('/clients/new', methods=['GET', 'POST'])
@login_required
def new():
    if request.method == 'POST':
        s = get_session()
        c = Customer(
            name=request.form.get('name', '').strip(),
            phone=request.form.get('phone', '').strip(),
            email=request.form.get('email', '').strip(),
            car_brand=request.form.get('car_brand', '').strip(),
            car_number=request.form.get('car_number', '').strip(),
            notes=request.form.get('notes', '').strip(),
        )
        s.add(c)
        s.commit()
        flash('Клиент добавлен', 'success')
        return redirect(url_for('customers.detail', cid=c.id))
    return render_template('customers/form.html', customer=None)


@bp.route('/clients/<int:cid>')
@login_required
def detail(cid):
    s = get_session()
    c = s.get(Customer, cid)
    if not c:
        abort(404)
    history = s.execute(
        select(Booking).where(Booking.customer_id == cid).order_by(Booking.starts_at.desc())
    ).scalars().all()
    total_paid = s.execute(
        select(func.coalesce(func.sum(Booking.total_kopecks), 0))
        .where(Booking.customer_id == cid, Booking.payment_status == PaymentStatus.PAID.value)
    ).scalar() or 0
    return render_template('customers/detail.html',
                           customer=c, history=history, total_paid=total_paid)


@bp.route('/clients/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def edit(cid):
    s = get_session()
    c = s.get(Customer, cid)
    if not c:
        abort(404)
    if request.method == 'POST':
        c.name = request.form.get('name', '').strip()
        c.phone = request.form.get('phone', '').strip()
        c.email = request.form.get('email', '').strip()
        c.car_brand = request.form.get('car_brand', '').strip()
        c.car_number = request.form.get('car_number', '').strip()
        c.notes = request.form.get('notes', '').strip()
        s.commit()
        flash('Клиент обновлён', 'success')
        return redirect(url_for('customers.detail', cid=cid))
    return render_template('customers/form.html', customer=c)

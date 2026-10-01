from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify
from flask_login import login_required
from sqlalchemy import select, delete
from collections import defaultdict

from ..db import get_session
from ..domain import Service, Instructor, Resource, Zone, Facility, ServiceCategory
from ..domain.models import (
    Specialization, InstructorSpecialization, InstructorServicePrice,
    InstructorResource, ResourceService, MembershipPlan,
)
from ..services.auth import manager_required, admin_required
from ..services import cascade, audit

bp = Blueprint('catalog', __name__)

WEEKDAYS = [
    ('mon', 'Пн'), ('tue', 'Вт'), ('wed', 'Ср'), ('thu', 'Чт'),
    ('fri', 'Пт'), ('sat', 'Сб'), ('sun', 'Вс'),
]

# ─── Услуги ────────────────────────────────────────────────────────

@bp.route('/services')
@login_required
def services():
    s = get_session()
    show_inactive = request.args.get('inactive') == '1'
    q = select(Service).order_by(Service.category, Service.base_price_kopecks)
    if not show_inactive:
        q = q.where(Service.active == True)
    rows = s.execute(q).scalars().all()
    grouped = defaultdict(list)
    for r in rows:
        grouped[r.category].append(r)
    return render_template('catalog/services.html',
                           grouped=grouped, show_inactive=show_inactive)


@bp.route('/services/<int:sid>/toggle', methods=['POST'])
@manager_required
def toggle_service(sid):
    s = get_session()
    svc = s.get(Service, sid)
    if not svc:
        abort(404)
    svc.active = not svc.active
    audit.log('update', 'service', sid,
              summary=f'{"Активирована" if svc.active else "Выключена"} услуга',
              after={'active': svc.active})
    s.commit()
    return redirect(url_for('catalog.services'))


@bp.route('/services/<int:sid>/edit', methods=['GET', 'POST'])
@manager_required
def edit_service(sid):
    s = get_session()
    svc = s.get(Service, sid)
    if not svc:
        abort(404)

    if request.method == 'POST':
        new_price_rub = int(request.form.get('price_rub') or 0)
        new_price_kop = new_price_rub * 100
        apply_to_bookings = request.form.get('apply_to_bookings') == '1'
        price_changed = new_price_kop != svc.base_price_kopecks

        svc.name = request.form.get('name', '').strip() or svc.name
        svc.duration_min = int(request.form.get('duration_min') or svc.duration_min)
        svc.group_size = int(request.form['group_size']) if request.form.get('group_size') else None
        svc.season = request.form.get('season', svc.season)
        svc.is_trial = bool(request.form.get('is_trial'))
        svc.is_kids = bool(request.form.get('is_kids'))
        svc.requires_instructor = bool(request.form.get('requires_instructor'))
        svc.description = request.form.get('description', '').strip()

        if price_changed:
            cascade.apply_service_price_change(
                sid, new_price_kop, also_apply_to_bookings=apply_to_bookings,
            )
        else:
            s.commit()
        flash('Услуга обновлена', 'success')
        return redirect(url_for('catalog.services'))

    # GET — показать форму
    preview_price = int(request.args.get('preview_price', '') or svc.base_price_kopecks // 100)
    preview_data = None
    if preview_price * 100 != svc.base_price_kopecks:
        preview_data = cascade.preview_service_price_change(sid, preview_price * 100)

    return render_template('catalog/service_form.html',
                           service=svc,
                           categories=[e.value for e in ServiceCategory],
                           preview_price=preview_price,
                           preview=preview_data)


@bp.route('/api/services/<int:sid>/cascade-preview')
@login_required
def cascade_preview(sid):
    try:
        new_price_rub = int(request.args.get('price_rub') or 0)
    except ValueError:
        return jsonify({'error': 'bad_price'}), 400
    return jsonify(cascade.preview_service_price_change(sid, new_price_rub * 100))


# ─── Специализации (справочник) ────────────────────────────────────

@bp.route('/specializations')
@login_required
def specializations():
    s = get_session()
    rows = s.execute(select(Specialization).order_by(Specialization.sort_order, Specialization.name)).scalars().all()
    return render_template('catalog/specializations.html', specs=rows)


@bp.route('/specializations/new', methods=['GET', 'POST'])
@manager_required
def new_specialization():
    s = get_session()
    if request.method == 'POST':
        s.add(Specialization(
            name=request.form.get('name', '').strip(),
            code=request.form.get('code', '').strip(),
            description=request.form.get('description', '').strip(),
            applicable_categories=request.form.getlist('applicable_categories'),
        ))
        s.commit()
        flash('Специализация добавлена', 'success')
        return redirect(url_for('catalog.specializations'))
    return render_template('catalog/specialization_form.html',
                           spec=None,
                           categories=[e.value for e in ServiceCategory])


@bp.route('/specializations/<int:sid>/edit', methods=['GET', 'POST'])
@manager_required
def edit_specialization(sid):
    s = get_session()
    spec = s.get(Specialization, sid)
    if not spec:
        abort(404)
    if request.method == 'POST':
        spec.name = request.form.get('name', '').strip()
        spec.description = request.form.get('description', '').strip()
        spec.applicable_categories = request.form.getlist('applicable_categories')
        spec.active = bool(request.form.get('active'))
        s.commit()
        flash('Специализация обновлена', 'success')
        return redirect(url_for('catalog.specializations'))
    return render_template('catalog/specialization_form.html',
                           spec=spec,
                           categories=[e.value for e in ServiceCategory])


# ─── Тренеры (конструктор) ─────────────────────────────────────────

@bp.route('/instructors')
@login_required
def instructors():
    s = get_session()
    rows = s.execute(
        select(Instructor).order_by(Instructor.active.desc(), Instructor.name)
    ).scalars().all()
    return render_template('catalog/instructors.html', instructors=rows)


@bp.route('/instructors/new', methods=['GET', 'POST'])
@manager_required
def new_instructor():
    s = get_session()
    if request.method == 'POST':
        i = Instructor(
            name=request.form.get('name', '').strip(),
            phone=request.form.get('phone', '').strip(),
            email=request.form.get('email', '').strip(),
            bio=request.form.get('bio', '').strip(),
            color=request.form.get('color') or '#C9A961',
        )
        s.add(i)
        s.flush()
        # специализации
        for sp_id in request.form.getlist('specializations'):
            s.add(InstructorSpecialization(instructor_id=i.id, specialization_id=int(sp_id)))
        audit.log('create', 'instructor', i.id, summary=f'Добавлен тренер: {i.name}')
        s.commit()
        flash('Тренер добавлен — настройте услуги, ресурсы и часы', 'success')
        return redirect(url_for('catalog.edit_instructor', iid=i.id))

    specs = s.execute(select(Specialization).where(Specialization.active == True)).scalars().all()
    return render_template('catalog/instructor_form.html',
                           instructor=None, all_specs=specs,
                           weekdays=WEEKDAYS,
                           all_services=[], all_resources=[])


@bp.route('/instructors/<int:iid>/edit', methods=['GET', 'POST'])
@manager_required
def edit_instructor(iid):
    s = get_session()
    i = s.get(Instructor, iid)
    if not i:
        abort(404)

    if request.method == 'POST':
        action = request.form.get('action', 'save')

        if action == 'save':
            i.name = request.form.get('name', '').strip()
            i.phone = request.form.get('phone', '').strip()
            i.email = request.form.get('email', '').strip()
            i.bio = request.form.get('bio', '').strip()
            i.color = request.form.get('color') or i.color
            # специализации
            s.execute(delete(InstructorSpecialization).where(InstructorSpecialization.instructor_id == iid))
            for sp_id in request.form.getlist('specializations'):
                s.add(InstructorSpecialization(instructor_id=iid, specialization_id=int(sp_id)))
            # ресурсы
            s.execute(delete(InstructorResource).where(InstructorResource.instructor_id == iid))
            for r_id in request.form.getlist('resources'):
                s.add(InstructorResource(instructor_id=iid, resource_id=int(r_id)))
            # working_hours
            wh = {}
            for code, _ in WEEKDAYS:
                open_t = request.form.get(f'wh_{code}_open')
                close_t = request.form.get(f'wh_{code}_close')
                if open_t and close_t:
                    wh[code] = [open_t, close_t]
            i.working_hours = wh
            audit.log('update', 'instructor', iid, summary=f'Обновлён профиль тренера: {i.name}')
            s.commit()
            flash('Профиль тренера сохранён', 'success')
            return redirect(url_for('catalog.edit_instructor', iid=iid))

        if action == 'set_service_price':
            service_id = int(request.form['service_id'])
            price_rub = int(request.form.get('price_rub') or 0)
            existing = s.execute(
                select(InstructorServicePrice).where(
                    InstructorServicePrice.instructor_id == iid,
                    InstructorServicePrice.service_id == service_id,
                )
            ).scalar_one_or_none()
            if price_rub == 0:
                # удалить override
                if existing:
                    s.delete(existing)
                    flash('Override цены удалён', 'success')
            else:
                if existing:
                    existing.price_kopecks = price_rub * 100
                else:
                    s.add(InstructorServicePrice(
                        instructor_id=iid, service_id=service_id,
                        price_kopecks=price_rub * 100,
                    ))
                flash('Цена тренера обновлена', 'success')
            s.commit()
            return redirect(url_for('catalog.edit_instructor', iid=iid))

    # GET
    specs = s.execute(select(Specialization).where(Specialization.active == True)
                      .order_by(Specialization.sort_order)).scalars().all()
    assigned_spec_ids = {sp.id for sp in i.specializations}
    # Авто-подбор услуг под специализации тренера
    applicable_cats = set()
    for sp in i.specializations:
        applicable_cats.update(sp.applicable_categories or [])
    relevant_services = s.execute(
        select(Service).where(Service.active == True).order_by(Service.category, Service.base_price_kopecks)
    ).scalars().all()
    # Помечаем «матчится ли под спец-ии»
    services_tagged = []
    for svc in relevant_services:
        services_tagged.append({
            'svc': svc,
            'matches_spec': svc.category in applicable_cats,
            'override_kopecks': next(
                (p.price_kopecks for p in i.service_prices if p.service_id == svc.id),
                None,
            ),
        })

    # Ресурсы
    all_resources = s.execute(
        select(Resource).where(Resource.active == True).order_by(Resource.sort_order)
    ).scalars().all()
    assigned_resource_ids = {r.resource_id for r in i.resource_assignments}

    return render_template('catalog/instructor_form.html',
                           instructor=i, all_specs=specs,
                           assigned_spec_ids=assigned_spec_ids,
                           weekdays=WEEKDAYS,
                           services_tagged=services_tagged,
                           all_resources=all_resources,
                           assigned_resource_ids=assigned_resource_ids,
                           applicable_cats=applicable_cats)


@bp.route('/instructors/<int:iid>/toggle', methods=['POST'])
@manager_required
def toggle_instructor(iid):
    s = get_session()
    i = s.get(Instructor, iid)
    if not i:
        abort(404)
    i.active = not i.active
    s.commit()
    return redirect(url_for('catalog.instructors'))


# ─── Ресурсы ───────────────────────────────────────────────────────

@bp.route('/resources')
@login_required
def resources():
    s = get_session()
    zones = s.execute(
        select(Zone).order_by(Zone.sort_order, Zone.name)
    ).scalars().all()
    return render_template('catalog/resources.html', zones=zones)


@bp.route('/resources/<int:rid>/edit', methods=['GET', 'POST'])
@manager_required
def edit_resource(rid):
    s = get_session()
    r = s.get(Resource, rid)
    if not r:
        abort(404)
    if request.method == 'POST':
        r.name = request.form.get('name', '').strip() or r.name
        r.code = request.form.get('code', '').strip() or r.code
        r.capacity = int(request.form.get('capacity') or r.capacity)
        r.season = request.form.get('season', r.season)
        r.color = request.form.get('color') or ''
        # Совместимые услуги
        s.execute(delete(ResourceService).where(ResourceService.resource_id == rid))
        for svc_id in request.form.getlist('services'):
            s.add(ResourceService(resource_id=rid, service_id=int(svc_id)))
        audit.log('update', 'resource', rid, summary=f'Обновлён ресурс: {r.name}')
        s.commit()
        flash('Ресурс обновлён', 'success')
        return redirect(url_for('catalog.resources'))

    all_services = s.execute(
        select(Service).where(Service.active == True).order_by(Service.category)
    ).scalars().all()
    assigned_service_ids = set(
        row[0] for row in s.execute(
            select(ResourceService.service_id).where(ResourceService.resource_id == rid)
        )
    )
    return render_template('catalog/resource_form.html',
                           resource=r, all_services=all_services,
                           assigned_service_ids=assigned_service_ids)


# ─── Membership tiers ──────────────────────────────────────────────

@bp.route('/memberships')
@login_required
def memberships():
    s = get_session()
    plans = s.execute(
        select(MembershipPlan).order_by(MembershipPlan.tier)
    ).scalars().all()
    return render_template('catalog/memberships.html', plans=plans)


@bp.route('/memberships/<int:pid>/edit', methods=['GET', 'POST'])
@admin_required
def edit_membership(pid):
    s = get_session()
    p = s.get(MembershipPlan, pid)
    if not p:
        abort(404)
    if request.method == 'POST':
        p.name = request.form.get('name', '').strip() or p.name
        p.tier = int(request.form.get('tier') or p.tier)
        p.price_kopecks = int(request.form.get('price_rub') or 0) * 100
        p.duration_days = int(request.form.get('duration_days') or 365)
        p.discount_percent = int(request.form.get('discount_percent') or 0)
        p.priority_booking_days = int(request.form.get('priority_booking_days') or 0)
        p.description = request.form.get('description', '').strip()
        p.active = bool(request.form.get('active'))
        audit.log('update', 'membership_plan', pid, summary=f'Обновлён tier: {p.name}')
        s.commit()
        flash('Тариф членства обновлён', 'success')
        return redirect(url_for('catalog.memberships'))
    return render_template('catalog/membership_form.html', plan=p)

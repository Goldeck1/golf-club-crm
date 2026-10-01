from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from sqlalchemy import select

from ..db import get_session
from ..domain import User, AuditLog, AppSetting
from ..services.auth import admin_required, hash_password

bp = Blueprint('admin', __name__)


@bp.route('/staff')
@admin_required
def staff():
    s = get_session()
    users = s.execute(select(User).order_by(User.role, User.name)).scalars().all()
    return render_template('admin/staff.html', users=users)


@bp.route('/staff/new', methods=['GET', 'POST'])
@admin_required
def new_staff():
    if request.method == 'POST':
        s = get_session()
        username = request.form.get('username', '').strip()
        if s.execute(select(User).where(User.username == username)).scalar_one_or_none():
            flash('Логин уже занят', 'error')
            return redirect(url_for('admin.new_staff'))
        s.add(User(
            username=username,
            name=request.form.get('name', '').strip(),
            role=request.form.get('role', 'staff'),
            password_hash=hash_password(request.form.get('password', 'changeme')),
        ))
        s.commit()
        flash('Сотрудник добавлен', 'success')
        return redirect(url_for('admin.staff'))
    return render_template('admin/staff_form.html')


@bp.route('/staff/<int:uid>/delete', methods=['POST'])
@admin_required
def delete_staff(uid):
    if uid == current_user.id:
        flash('Нельзя удалить самого себя', 'error')
        return redirect(url_for('admin.staff'))
    s = get_session()
    u = s.get(User, uid)
    if u:
        s.delete(u)
        s.commit()
        flash('Сотрудник удалён', 'success')
    return redirect(url_for('admin.staff'))


# ─── Audit log ─────────────────────────────────────────────────────

@bp.route('/audit')
@admin_required
def audit():
    s = get_session()
    entity = request.args.get('entity', '')
    action = request.args.get('action', '')
    q = select(AuditLog).order_by(AuditLog.at.desc()).limit(500)
    if entity:
        q = q.where(AuditLog.entity == entity)
    if action:
        q = q.where(AuditLog.action == action)
    entries = s.execute(q).scalars().all()
    return render_template('admin/audit.html',
                           entries=entries, entity=entity, action=action)


# ─── Settings ──────────────────────────────────────────────────────

@bp.route('/settings', methods=['GET', 'POST'])
@admin_required
def settings():
    s = get_session()
    if request.method == 'POST':
        form_type = request.form.get('form', '')
        if form_type == 'season':
            value = request.form.get('season', 'auto')
            setting = s.get(AppSetting, 'season_mode')
            if setting:
                setting.value = value
            else:
                s.add(AppSetting(key='season_mode', value=value))
            s.commit()
            flash('Сезон обновлён', 'success')
        return redirect(url_for('admin.settings'))

    season_mode = (s.get(AppSetting, 'season_mode') or AppSetting(value='auto')).value
    return render_template('admin/settings.html', season_mode=season_mode)

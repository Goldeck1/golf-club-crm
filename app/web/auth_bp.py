from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, current_user

from ..db import get_session
from ..domain import User, AuditAction
from ..services.auth import verify_password
from ..services import audit

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        s = get_session()
        user = s.query(User).filter_by(username=username).first()

        if user and user.active and verify_password(user, password):
            login_user(user, remember=True)
            user.last_login_at = datetime.utcnow()
            audit.log(AuditAction.LOGIN.value, 'user', user.id,
                      summary=f'Вход: {user.username}')
            s.commit()
            return redirect(request.args.get('next') or url_for('dashboard.index'))

        # failed login
        if user:
            audit.log(AuditAction.LOGIN_FAILED.value, 'user', user.id,
                      summary=f'Неудачный вход: {username}')
            s.commit()
        flash('Неверный логин или пароль', 'error')

    return render_template('auth/login.html')


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

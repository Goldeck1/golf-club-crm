from flask import Flask, render_template
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import select

from .config import Config
from .db import init_engine, Base
from . import db as _db


login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Требуется вход в систему'
login_manager.login_message_category = 'info'

csrf = CSRFProtect()


def create_app(config_class=Config) -> Flask:
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config.from_object(config_class)

    init_engine(app.config['SQLALCHEMY_DATABASE_URI'], echo=app.config['SQLALCHEMY_ECHO'])

    # models registered with Base
    from . import domain  # noqa: F401

    Base.metadata.create_all(bind=_get_engine())

    # seed
    from .seed import seed_if_empty
    with app.app_context():
        seed_if_empty()

    login_manager.init_app(app)
    csrf.init_app(app)

    @login_manager.user_loader
    def _load(uid):
        from .domain import User
        return _db.db_session.get(User, int(uid))

    @app.teardown_appcontext
    def _remove_session(_exc):
        if _db.db_session is not None:
            _db.db_session.remove()

    # Context processor: helpers for templates
    @app.context_processor
    def _ctx():
        from .services.scheduler import current_season
        return {
            'CLUB_NAME': app.config['CLUB_NAME'],
            'current_season': current_season(),
        }

    # Filters
    @app.template_filter('rub')
    def _rub(kopecks):
        if kopecks is None:
            return '0 ₽'
        rub = int(kopecks) // 100
        return f'{rub:,}'.replace(',', ' ') + ' ₽'

    @app.template_filter('hm')
    def _hm(dt):
        return dt.strftime('%H:%M') if dt else ''

    @app.template_filter('ymd')
    def _ymd(dt):
        return dt.strftime('%Y-%m-%d') if dt else ''

    @app.template_filter('status_label')
    def _status_label(s):
        m = {
            'draft': 'Черновик',
            'held': 'Удержание',
            'confirmed': 'Подтверждена',
            'checked_in': 'Зарегистрирована',
            'completed': 'Завершена',
            'cancelled': 'Отменена',
            'no_show': 'Неявка',
            'paid': 'Оплачено',
            'pending': 'Не оплачено',
            'authorized': 'Авторизовано',
            'refunded': 'Возврат',
            'partially_refunded': 'Частичный возврат',
            'failed': 'Ошибка оплаты',
            'canceled': 'Отменена',
            'requires_action': 'Требует действия',
        }
        return m.get(s, s)

    # Register blueprints
    from .web import register_blueprints
    register_blueprints(app)

    @app.errorhandler(403)
    def _403(_e):
        return render_template('errors/403.html'), 403

    @app.errorhandler(404)
    def _404(_e):
        return render_template('errors/404.html'), 404

    return app


def _get_engine():
    from .db import engine
    return engine

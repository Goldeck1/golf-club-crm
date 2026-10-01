from flask import Flask


def register_blueprints(app: Flask):
    from .auth_bp import bp as auth_bp
    from .calendar_bp import bp as calendar_bp
    from .booking_bp import bp as booking_bp
    from .customer_bp import bp as customer_bp
    from .catalog_bp import bp as catalog_bp
    from .admin_bp import bp as admin_bp
    from .dashboard_bp import bp as dashboard_bp
    from .search_bp import bp as search_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(calendar_bp)
    app.register_blueprint(booking_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(catalog_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(search_bp)

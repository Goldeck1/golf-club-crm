"""Ad-hoc SQLite migrations. We run create_all() for new tables, but SQLAlchemy
doesn't ALTER existing tables. This module applies minimal patches.

Each function is idempotent: checks PRAGMA table_info first.
"""
from sqlalchemy import text
from sqlalchemy.engine import Engine


def _column_exists(conn, table: str, column: str) -> bool:
    cols = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(c[1] == column for c in cols)


def apply_migrations(engine: Engine):
    if not engine.url.get_backend_name() == "sqlite":
        return

    with engine.begin() as conn:
        # services.tags JSON default '[]'
        if not _column_exists(conn, "services", "tags"):
            conn.execute(text("ALTER TABLE services ADD COLUMN tags JSON DEFAULT '[]'"))
            conn.execute(text("UPDATE services SET tags = '[]' WHERE tags IS NULL"))

        # instructors.tags
        if not _column_exists(conn, "instructors", "tags"):
            conn.execute(text("ALTER TABLE instructors ADD COLUMN tags JSON DEFAULT '[]'"))
            conn.execute(text("UPDATE instructors SET tags = '[]' WHERE tags IS NULL"))

        # instructors.hourly_payout_kopecks
        if not _column_exists(conn, "instructors", "hourly_payout_kopecks"):
            conn.execute(text("ALTER TABLE instructors ADD COLUMN hourly_payout_kopecks BIGINT DEFAULT 0"))

        # bookings.coupon_code — promo tracking
        if not _column_exists(conn, "bookings", "coupon_code"):
            conn.execute(text("ALTER TABLE bookings ADD COLUMN coupon_code VARCHAR(64) DEFAULT ''"))

        # Top up driving-range lanes to D1..D24 (was D1..D4). Idempotent.
        _ensure_24_range_lanes(conn)

        # Seed "МГГК-specific" staff accounts + replace default trainers. Idempotent.
        _sync_mggk_staff_and_trainers(conn)

        # Subscription-pass (абонемент) columns.
        if not _column_exists(conn, "membership_plans", "covers_training"):
            conn.execute(text(
                "ALTER TABLE membership_plans ADD COLUMN covers_training BOOLEAN DEFAULT 0"
            ))
        if not _column_exists(conn, "membership_plans", "max_trainings"):
            conn.execute(text(
                "ALTER TABLE membership_plans ADD COLUMN max_trainings INTEGER DEFAULT 0"
            ))
        if not _column_exists(conn, "memberships", "trainings_used"):
            conn.execute(text(
                "ALTER TABLE memberships ADD COLUMN trainings_used INTEGER DEFAULT 0"
            ))

        # users.instructor_id — FK to instructors for instructor-role accounts
        if not _column_exists(conn, "users", "instructor_id"):
            conn.execute(text(
                "ALTER TABLE users ADD COLUMN instructor_id INTEGER REFERENCES instructors(id)"
            ))

        # customers.created_by_id — кто завёл клиента (для скоупа тренера)
        if not _column_exists(conn, "customers", "created_by_id"):
            conn.execute(text(
                "ALTER TABLE customers ADD COLUMN created_by_id INTEGER REFERENCES users(id)"
            ))

        # instructors.pending_working_hours / pending_effective_from — отложенный график
        if not _column_exists(conn, "instructors", "pending_working_hours"):
            conn.execute(text(
                "ALTER TABLE instructors ADD COLUMN pending_working_hours JSON"
            ))
        if not _column_exists(conn, "instructors", "pending_effective_from"):
            conn.execute(text(
                "ALTER TABLE instructors ADD COLUMN pending_effective_from DATE"
            ))

        # Seed instructor user accounts, link them to their Instructor rows. Idempotent.
        _sync_instructor_user_accounts(conn)


def _ensure_24_range_lanes(conn):
    """Ensure Resource rows D1..D24 exist and are linked to driving-range services.
    Reads/writes via raw SQL to avoid ORM cycles during startup migrations.
    """
    rows = conn.execute(text("SELECT code FROM resources WHERE code LIKE 'D%'")).fetchall()
    existing = {r[0] for r in rows}
    target = {f"D{i}" for i in range(1, 25)}
    missing = sorted(target - existing, key=lambda c: int(c[1:]))
    if not missing:
        return

    # Pull the driving-zone / resource-type ids from an existing D lane (D1 is seeded).
    ref = conn.execute(text(
        "SELECT zone_id, resource_type_id, season FROM resources WHERE code = 'D1'"
    )).fetchone()
    if not ref:
        return  # fresh DB — seed will create the full set
    zone_id, rt_id, season = ref[0], ref[1], ref[2]

    # Copy open hours from D1's first availability rule (if any).
    rule_row = conn.execute(text(
        "SELECT open_time, close_time, season, weekday FROM availability_rules "
        "WHERE resource_id = (SELECT id FROM resources WHERE code='D1') LIMIT 1"
    )).fetchone()

    # Services that D1 is bound to — new lanes inherit the same bindings.
    d1_services = [
        row[0] for row in conn.execute(text(
            "SELECT service_id FROM resource_services WHERE resource_id = "
            "(SELECT id FROM resources WHERE code='D1')"
        )).fetchall()
    ]

    for code in missing:
        n = int(code[1:])
        conn.execute(text(
            "INSERT INTO resources (zone_id, resource_type_id, name, code, sort_order, "
            "season, capacity, color, meta, active, created_at, updated_at) "
            "VALUES (:zone, :rt, :name, :code, :sort, :season, 1, '#2E9A6A', '{}', 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {
            "zone": zone_id, "rt": rt_id,
            "name": f"Драйвинг-рэндж {n}", "code": code,
            "sort": n, "season": season,
        })
        rid = conn.execute(text("SELECT id FROM resources WHERE code = :c"),
                           {"c": code}).scalar()
        if rule_row and rid:
            open_t, close_t, rule_season, weekday = rule_row
            conn.execute(text(
                "INSERT INTO availability_rules (resource_id, weekday, open_time, "
                "close_time, season, created_at, updated_at) "
                "VALUES (:rid, :wd, :o, :c, :s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), {"rid": rid, "wd": weekday, "o": open_t, "c": close_t, "s": rule_season})
        if rid and d1_services:
            for sid in d1_services:
                conn.execute(text(
                    "INSERT OR IGNORE INTO resource_services (resource_id, service_id) "
                    "VALUES (:rid, :sid)"
                ), {"rid": rid, "sid": sid})


# ── МГГК staff + trainer roster sync ─────────────────────────────────────────
# Target roster (per product owner):
#   Руководители (admin role):  Дини (dini)
#   Администраторы (staff role): Ольга (olga), Арби (arbi)
#   Тренеры: Вероника Антропова, Карина Антропова, Сергей Зубрилен, Дарья (стажёр)
#
# Applied on every startup, but guarded by an AppSetting marker so it only runs once.
_STAFF_ROSTER_MARKER = "mggk_roster_v1_applied"

_MGGK_USERS = [
    # (username, name, role, password_plain)
    ("dini", "Дини", "admin", "dini"),
    ("olga", "Ольга", "staff", "olga"),
    ("arbi", "Арби", "staff", "arbi"),
]

_MGGK_TRAINERS = [
    # (name, specialization, color)
    ("Вероника Антропова", "Тренер", "#2E9A6A"),
    ("Карина Антропова", "Тренер", "#3A6EA5"),
    ("Сергей Зубрилен", "Тренер", "#C9A961"),
    ("Дарья", "Стажёр", "#8B5A96"),
]


def _sync_mggk_staff_and_trainers(conn):
    """Idempotently seed МГГК accounts + replace default trainers. Safe to run
    every boot — guarded by an app_settings marker so it runs at most once."""
    row = conn.execute(text(
        "SELECT value FROM app_settings WHERE key = :k"
    ), {"k": _STAFF_ROSTER_MARKER}).fetchone()
    if row:
        return

    # Users table may not exist yet if this is a fresh DB — create_all happens before us
    # but seed_if_empty runs AFTER migrations. If there are no users, we skip: seed will
    # create the canonical roster.
    user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
    if user_count == 0:
        return  # fresh DB, seed will handle

    # Lazy import to avoid circular import at module load time.
    from .security import hash_password

    for username, display_name, role, password in _MGGK_USERS:
        existing = conn.execute(text(
            "SELECT id FROM users WHERE username = :u"
        ), {"u": username}).fetchone()
        if existing:
            continue
        conn.execute(text(
            "INSERT INTO users (username, password_hash, name, email, role, "
            "telegram_chat_id, active, created_at, updated_at) "
            "VALUES (:u, :p, :n, '', :r, '', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"u": username, "p": hash_password(password), "n": display_name, "r": role})

    # Deactivate legacy default trainers (by exact name) if they exist — preserves
    # historical bookings by not deleting, just hiding.
    legacy_names = (
        "Матросов Алексей Викторович",
        "Иванов Иван Иванович",
        "Петрова Елена Сергеевна",
    )
    for name in legacy_names:
        conn.execute(text(
            "UPDATE instructors SET active = 0 WHERE name = :n"
        ), {"n": name})

    # Add new МГГК trainers if missing.
    for name, spec, color in _MGGK_TRAINERS:
        existing = conn.execute(text(
            "SELECT id FROM instructors WHERE name = :n"
        ), {"n": name}).fetchone()
        if existing:
            # Make sure it's active and has the right specialization.
            conn.execute(text(
                "UPDATE instructors SET active = 1, specialization = :s "
                "WHERE id = :id"
            ), {"s": spec, "id": existing[0]})
            continue
        conn.execute(text(
            "INSERT INTO instructors (name, specialization, color, bio, avatar_url, "
            "phone, email, working_hours, tags, hourly_payout_kopecks, active, "
            "created_at, updated_at) "
            "VALUES (:n, :s, :c, '', '', '', '', '{}', '[]', 0, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"n": name, "s": spec, "c": color})

    conn.execute(text(
        "INSERT INTO app_settings (key, value, created_at, updated_at) "
        "VALUES (:k, 'true', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value = 'true'"
    ), {"k": _STAFF_ROSTER_MARKER})


# Link each trainer to their own login account.
_INSTRUCTOR_USERS = [
    # (username, password, linked instructor name)
    ("veronika", "veronika", "Вероника Антропова"),
    ("karina", "karina", "Карина Антропова"),
    ("sergey", "sergey", "Сергей Зубрилен"),
    ("darya", "darya", "Дарья"),
]


def _sync_instructor_user_accounts(conn):
    """Create a `User` per trainer (role=instructor) linked via users.instructor_id
    so the trainer's personal dashboard shows only their own bookings.
    Idempotent: skips users that already exist."""
    # Skip if the users table isn't there yet (fresh DB — seed will run later).
    user_count = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
    if user_count == 0:
        return

    from .security import hash_password

    for username, password, instr_name in _INSTRUCTOR_USERS:
        instr_row = conn.execute(text(
            "SELECT id FROM instructors WHERE name = :n"
        ), {"n": instr_name}).fetchone()
        if not instr_row:
            continue  # trainer not yet seeded — migration will re-run next boot
        instr_id = instr_row[0]

        existing = conn.execute(text(
            "SELECT id FROM users WHERE username = :u"
        ), {"u": username}).fetchone()
        if existing:
            # Ensure the link is set, even if user already existed from a prior
            # migration run before instructor_id column existed.
            conn.execute(text(
                "UPDATE users SET instructor_id = :iid, role = 'instructor' "
                "WHERE id = :uid AND (instructor_id IS NULL OR instructor_id != :iid)"
            ), {"iid": instr_id, "uid": existing[0]})
            continue
        conn.execute(text(
            "INSERT INTO users (username, password_hash, name, email, role, "
            "telegram_chat_id, active, instructor_id, created_at, updated_at) "
            "VALUES (:u, :p, :n, '', 'instructor', '', 1, :iid, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {"u": username, "p": hash_password(password), "n": instr_name, "iid": instr_id})

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker


class Base(DeclarativeBase):
    pass


engine = None
SessionLocal = None
db_session = None


def init_engine(database_uri: str, echo: bool = False):
    """Initialize engine + scoped session. Called from app factory."""
    global engine, SessionLocal, db_session
    engine = create_engine(database_uri, echo=echo, future=True)

    if database_uri.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def _sqlite_pragmas(dbapi_conn, _):
            cur = dbapi_conn.cursor()
            cur.execute('PRAGMA journal_mode=WAL')
            cur.execute('PRAGMA foreign_keys=ON')
            cur.close()

    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db_session = scoped_session(SessionLocal)
    return engine


def get_session():
    """Shortcut used inside request handlers."""
    return db_session()

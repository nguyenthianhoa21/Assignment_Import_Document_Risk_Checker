from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings


def build_engine() -> Engine:
    """Create a SQLAlchemy engine for PostgreSQL.

    Falls back to SQLite only when PostgreSQL cannot be reached, keeping the
    backend runnable locally without any external database service.
    """
    url = settings.database_url
    if not url.startswith("postgresql"):
        return create_engine(url, future=True)
    try:
        engine = create_engine(url, future=True, pool_pre_ping=True)
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return engine
    except Exception:
        fallback_url = "sqlite:///./risk_checker_fallback.db"
        return create_engine(fallback_url, future=True, connect_args={"check_same_thread": False})


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

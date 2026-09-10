import socket
from collections.abc import Generator
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


def get_db() -> Generator[Session, None, None]:
    """Dependency that yields a database session and ensures cleanup."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_connection() -> bool:
    """Verify database connectivity by executing a lightweight SELECT 1 query."""
    try:
        parsed = urlparse(settings.DATABASE_URL)
        host = parsed.hostname or "localhost"
        port = parsed.port or 5432
        # Quick socket check with 1s timeout prevents lengthy OS TCP connect timeouts
        with socket.create_connection((host, port), timeout=1.0):
            pass

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False

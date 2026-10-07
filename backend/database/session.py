"""
TestSphere-AI — Database Session & Connection Management.

Configures database connection using SQLAlchemy.
Defaults to local SQLite without creating unnecessary tables.
"""

from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.config import settings

# Engine setup
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

# For in-memory sqlite testing or standard file-based sqlite
if settings.DATABASE_URL == "sqlite:///:memory:":
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
        poolclass=StaticPool,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args=connect_args,
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Declarative Base for models (SQLAlchemy 2.0 style)
class Base(DeclarativeBase):
    pass


def get_db() -> Generator:
    """Dependency provider for FastAPI route handlers."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> bool:
    """Verify database connection and initialize Member 3 tables."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # Import models so Base.metadata discovers all Member 3 tables
        import backend.models  # noqa: F401
        Base.metadata.create_all(bind=engine)
        # Auto-seed initial real data if database has no projects
        from backend.database.seed import seed_database_if_empty
        with SessionLocal() as db:
            seed_database_if_empty(db)
        return True
    except Exception as exc:
        raise RuntimeError(f"Database initialization failed: {exc}") from exc


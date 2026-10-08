"""Database connection and session factory using SQLAlchemy 2.x."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

connect_args: dict[str, bool] = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Provide a transactional database session scope."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Create database tables on startup.

    Note on Schema Evolution (Future Scope):
    Base.metadata.create_all is ideal for rapid development and testing.
    In production environments, Alembic migrations should be used for zero-downtime
    DDL versioning and rollback capability.
    """
    Base.metadata.create_all(bind=engine)

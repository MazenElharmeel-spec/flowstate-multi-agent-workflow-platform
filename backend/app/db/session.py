"""Database session and connection management."""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from backend.app.core.config import get_settings

settings = get_settings()

# Ensure local SQLite directory exists if using SQLite
if "sqlite" in settings.DATABASE_URL:
    data_dir = Path("./data")
    data_dir.mkdir(parents=True, exist_ok=True)

# Build async engine with connection pooling options where appropriate
connect_args = {"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
pool_kwargs: dict[str, Any] = {"poolclass": NullPool} if "sqlite" in settings.DATABASE_URL else {}
if "sqlite" not in settings.DATABASE_URL:
    pool_kwargs.update(
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_pre_ping=True,
    )

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    future=True,
    connect_args=connect_args,
    **pool_kwargs,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for obtaining an asynchronous database session."""
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables in the database (used in tests and standalone mode)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

# Base for the ORM models (the tables).
Base = declarative_base()

# Config from environment (12-factor). The secret NEVER goes in the code.
# If DATABASE_URL is not defined, we fail fast and clearly (no fallback with a secret).
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Inject it via environment "
        "(docker-compose .env in local, Key Vault in Azure)."
    )

# The async engine: a pool of reusable connections.
engine = create_async_engine(
    DATABASE_URL,
    pool_recycle=3600,    # recycles connections every hour (enough to avoid dead connections)
    echo=False,
)

# Async session factory — one session per unit of work.
AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncSession:
    """Provides an async session (used as a dependency in FastAPI)."""
    async with AsyncSessionLocal() as session:
        yield session
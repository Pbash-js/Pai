from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import inspect
import asyncio

from config import ASYNC_DATABASE_URL

# Create async engine instead of sync engine
engine = create_async_engine(ASYNC_DATABASE_URL)
AsyncSessionLocal = sessionmaker(
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    bind=engine
)
Base = declarative_base()

# Async dependency to get DB session
async def get_db():
    async with AsyncSessionLocal() as db:
        try:
            yield db
        finally:
            await db.close()

async def init_db():
    """Initialize the database by creating all tables asynchronously."""
    from .models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def check_db_initialized():
    """Check if database tables have been created asynchronously."""
    async with engine.begin() as conn:
        # We need to use run_sync because inspect is not async-aware
        inspector = await conn.run_sync(lambda sync_conn: inspect(sync_conn))
        table_names = inspector.get_table_names()
        # Return True if any tables exist in the database
        return len(table_names) > 0
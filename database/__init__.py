# database/__init__.py (or relevant file)

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import inspect # Ensure inspect is imported
import asyncio

from config import ASYNC_DATABASE_URL

# Create async engine instead of sync engine
engine = create_async_engine(ASYNC_DATABASE_URL) # Add echo=True for debugging SQL if needed
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
            await db.close() # Ensure session is closed

async def init_db():
    """Initialize the database by creating all tables asynchronously."""
    # Make sure models are imported *before* create_all is called
    # This is often done implicitly if Base is defined after models,
    # but explicit import here can sometimes help if Base is separate.
    from . import models # Or adjust path as needed
    async with engine.begin() as conn:
        # Base.metadata needs to be populated when create_all is called
        await conn.run_sync(Base.metadata.create_all)

async def check_db_initialized():
    """Check if database tables have been created asynchronously."""
    async with engine.begin() as conn:
        # Run both inspect() and get_table_names() within the run_sync context
        # This ensures all synchronous I/O happens inside the greenlet wrapper.
        table_names = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_table_names()
        )
        # table_names is now the list returned from the synchronous context
        return len(table_names) > 0

# Removed the synchronous check_db_initialized function if it existed before.
# We are now consistently using the async version via asyncio.run() in run.py
from sqlalchemy import create_engine, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from config import DATABASE_URL

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize the database by creating all tables."""
    from .models import Base
    Base.metadata.create_all(bind=engine)


def check_db_initialized():
    """Check if database tables have been created."""
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    # Return True if any tables exist in the database
    return len(table_names) > 0
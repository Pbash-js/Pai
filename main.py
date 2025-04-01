import logging
import uvicorn
from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from starlette.middleware.sessions import SessionMiddleware

from api.routes import router as api_router
from database import init_db
from config import HOST, PORT

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan setup and teardown."""
    # Initialize database on startup
    logger.info("Initializing database...")
    init_db()
    logger.info("Database initialized successfully.")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down application...")


# Create FastAPI app
app = FastAPI(
    title="WhatsApp Reminder & Calendar Bot",
    description="A WhatsApp bot for reminders and calendar events",
    version="1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SessionMiddleware, secret_key="your-secret-key") # Add middleware to the app

# Include routers
app.include_router(api_router, prefix="/api")


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "WhatsApp Reminder & Calendar Bot API",
        "status": "running"
    }


if __name__ == "__main__":
    logger.info(f"Starting server on {HOST}:{PORT}")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
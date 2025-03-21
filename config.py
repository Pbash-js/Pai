import os
from pathlib import Path
from dotenv import load_dotenv
import logging
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("config")

# Load environment variables from .env file
load_dotenv(".env")

# Base directory
BASE_DIR = Path(__file__).resolve().parent

# API Keys
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_BUSINESS_ACCOUNT_ID = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID")
TELEGRAM_BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN")
# Database settings
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/reminder_bot.db")

# LLM settings
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash-lite")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

# Scheduler settings
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


logger.info(f"BASE_DIR {BASE_DIR}")
logger.info(f"GEMINI_API_KEY {GEMINI_API_KEY}")
logger.info(f"WHATSAPP_API_KEY {WHATSAPP_API_KEY}")
logger.info(f"WHATSAPP_PHONE_NUMBER_ID {WHATSAPP_PHONE_NUMBER_ID}")
logger.info(f"WHATSAPP_BUSINESS_ACCOUNT_ID {WHATSAPP_BUSINESS_ACCOUNT_ID}")
logger.info(f"DATABASE_URL {DATABASE_URL}")
logger.info(f"LLM_MODEL {LLM_MODEL}")
logger.info(f"REDIS_URL {REDIS_URL}")

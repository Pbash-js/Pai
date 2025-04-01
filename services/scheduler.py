import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Any

from celery import Celery
from celery.schedules import crontab

from config import REDIS_URL
from database import crud, AsyncSessionLocal
#changes
from whatsapp.client import TelegramClient
from services.reminder import ReminderService
import asyncio

logger = logging.getLogger(__name__)

# Create Celery app
celery_app = Celery("reminder_bot", broker=REDIS_URL)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "check-reminders-every-minute": {
            "task": "services.scheduler.check_reminders",
            "schedule": crontab(minute="*"),  # Every minute
        }
    },
    broker_connection_retry_on_startup=True
)


@celery_app.task
async def check_reminders():
    """
    Check for due reminders and send notifications.
    """
    logger.info("Checking for due reminders...")
    
    async def _async_check_reminders():
        # Your async logic here
        print("Checking reminders asynchronously...")
        # Examples of async operations:
        # await db.fetch_all("SELECT * FROM reminders WHERE time <= NOW()")
        # for reminder in reminders:
        #     await send_notification(reminder)

        try:
            # Get database session
            db = AsyncSessionLocal()
            
            # Create services
            reminder_service = ReminderService(db)
            telegram_client = TelegramClient()
            
            # Process due reminders
            notifications = reminder_service.process_due_reminders()
            
            # Send notifications
            for notification in notifications:
                #logger.info(f"Sending notification to {notification['phone_number']}: {notification['message']}")
                telegram_client.send_message(
                    message=notification["message"],
                    chat_id=notification["phone_number"]
                )
            
            #logger.info(f"Processed {len(notifications)} reminder notifications")
        
        except Exception as e:
            logger.error(f"Error checking reminders: {e}")
        
        finally:
            await db.close()

    # Run the async function in a new event loop
    asyncio.run(_async_check_reminders())
    return "Reminders checked"



import logging
from datetime import datetime, timedelta
from typing import Callable, Dict, Any

from celery import Celery
from celery.schedules import crontab

from config import REDIS_URL
from database import crud, SessionLocal
from whatsapp.client import WhatsAppClient
from services.reminder import ReminderService

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
    }
)


@celery_app.task
def check_reminders():
    """
    Check for due reminders and send notifications.
    """
    logger.info("Checking for due reminders...")
    
    try:
        # Get database session
        db = SessionLocal()
        
        # Create services
        reminder_service = ReminderService(db)
        whatsapp_client = WhatsAppClient()
        
        # Process due reminders
        notifications = reminder_service.process_due_reminders()
        
        # Send notifications
        for notification in notifications:
            logger.info(f"Sending notification to {notification['phone_number']}: {notification['message']}")
            whatsapp_client.send_message(
                recipient_phone=notification["phone_number"],
                message=notification["message"]
            )
        
        logger.info(f"Processed {len(notifications)} reminder notifications")
    
    except Exception as e:
        logger.error(f"Error checking reminders: {e}")
    
    finally:
        db.close()
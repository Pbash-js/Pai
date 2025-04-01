import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import and_, or_, select, update
from sqlalchemy.future import select

from .models import User, Reminder, CalendarEvent, Session, RepeatFrequency


# User operations
async def get_user_by_phone(db: AsyncSession, phone_number: str) -> Optional[User]:
    result = await db.execute(select(User).filter(User.phone_number == phone_number))
    return result.scalars().first()

async def get_user_by_id(db: AsyncSession, user_id: str) -> Optional[User]:
    result = await db.execute(select(User).filter(User.id == user_id))
    return result.scalars().first()

async def create_user(db: AsyncSession, phone_number: str) -> User:
    user = User(phone_number=phone_number)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user

async def update_user_google_info(db: AsyncSession, telegram_id: int, google_info: dict):
    """Update user with Google account information."""
    result = await db.execute(select(User).filter(User.phone_number == telegram_id))
    user = result.scalars().first()
    if user:
        user.google_id = google_info.get("google_id")
        user.email = google_info.get("email")
        user.name = google_info.get("name")
        await db.commit()
        return user
    return None

async def get_or_create_user(db: AsyncSession, phone_number: str) -> User:
    user = await get_user_by_phone(db, phone_number)
    if not user:
        user = await create_user(db, phone_number)
    
    # Update last active timestamp
    user.last_active = datetime.utcnow()
    await db.commit()
    await db.refresh(user)
    return user

async def user_set_google_id(db: AsyncSession, user_id: int, google_id: str) -> Optional[User]:
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()
    if not user:
        return None
    user.google_id = google_id
    await db.commit() 
    await db.refresh(user)
    return user

# Reminder operations
async def create_reminder(
    db: AsyncSession,
    user_id: int,
    message: str,
    scheduled_time: datetime,
    is_recurring: bool = False,
    repeat_frequency: RepeatFrequency = RepeatFrequency.NONE,
    repeat_interval: int = 0
) -> Reminder:
    reminder = Reminder(
        user_id=user_id,
        message=message,
        scheduled_time=scheduled_time,
        is_recurring=is_recurring,
        repeat_frequency=repeat_frequency,
        repeat_interval=repeat_interval
    )
    db.add(reminder)
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def get_user_reminders(db: AsyncSession, user_id: int, active_only: bool = True) -> List[Reminder]:
    query = select(Reminder).filter(Reminder.user_id == user_id)
    if active_only:
        query = query.filter(Reminder.is_active == True)
    result = await db.execute(query.order_by(Reminder.scheduled_time))
    return result.scalars().all()


async def get_upcoming_reminders(db: AsyncSession, user_id: int, days: int = 7) -> List[Reminder]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    query = select(Reminder).filter(
        and_(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= now,
            Reminder.scheduled_time <= end_date,
            Reminder.is_active == True
        )
    ).order_by(Reminder.scheduled_time)
    result = await db.execute(query)
    return result.scalars().all()


async def get_due_reminders(db: AsyncSession) -> List[Reminder]:
    now = datetime.utcnow()
    query = select(Reminder).filter(
        and_(
            Reminder.scheduled_time <= now,
            Reminder.is_active == True
        )
    )
    result = await db.execute(query)
    return result.scalars().all()


async def update_reminder(db: AsyncSession, reminder_id: int, **kwargs) -> Optional[Reminder]:
    result = await db.execute(select(Reminder).filter(Reminder.id == reminder_id))
    reminder = result.scalars().first()
    if not reminder:
        return None
    
    for key, value in kwargs.items():
        if hasattr(reminder, key):
            setattr(reminder, key, value)
    
    await db.commit()
    await db.refresh(reminder)
    return reminder


async def delete_reminder(db: AsyncSession, reminder_id: int) -> bool:
    result = await db.execute(select(Reminder).filter(Reminder.id == reminder_id))
    reminder = result.scalars().first()
    if not reminder:
        return False
    
    reminder.is_active = False
    await db.commit()
    return True


# Calendar event operations
async def create_calendar_event(
    db: AsyncSession,
    user_id: int,
    title: str,
    start_time: datetime,
    end_time: Optional[datetime] = None,
    location: Optional[str] = None,
    participants: Optional[str] = None
) -> CalendarEvent:
    event = CalendarEvent(
        user_id=user_id,
        title=title,
        start_time=start_time,
        end_time=end_time,
        location=location,
        participants=participants
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def get_user_calendar_events(db: AsyncSession, user_id: int, active_only: bool = True) -> List[CalendarEvent]:
    query = select(CalendarEvent).filter(CalendarEvent.user_id == user_id)
    if active_only:
        query = query.filter(CalendarEvent.is_active == True)
    result = await db.execute(query.order_by(CalendarEvent.start_time))
    return result.scalars().all()


async def get_upcoming_events(db: AsyncSession, user_id: int, days: int = 7) -> List[CalendarEvent]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    query = select(CalendarEvent).filter(
        and_(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= end_date,
            CalendarEvent.is_active == True
        )
    ).order_by(CalendarEvent.start_time)
    result = await db.execute(query)
    return result.scalars().all()


async def update_calendar_event(db: AsyncSession, event_id: int, **kwargs) -> Optional[CalendarEvent]:
    result = await db.execute(select(CalendarEvent).filter(CalendarEvent.id == event_id))
    event = result.scalars().first()
    if not event:
        return None
    
    for key, value in kwargs.items():
        if hasattr(event, key):
            setattr(event, key, value)
    
    await db.commit()
    await db.refresh(event)
    return event


async def delete_calendar_event(db: AsyncSession, event_id: int) -> bool:
    result = await db.execute(select(CalendarEvent).filter(CalendarEvent.id == event_id))
    event = result.scalars().first()
    if not event:
        return False
    
    event.is_active = False
    await db.commit()
    return True


async def find_calendar_event_by_title(db: AsyncSession, user_id: int, title: str) -> Optional[CalendarEvent]:
    query = select(CalendarEvent).filter(
        and_(
            CalendarEvent.user_id == user_id,
            CalendarEvent.title.ilike(f"%{title}%"),
            CalendarEvent.is_active == True
        )
    )
    result = await db.execute(query)
    return result.scalars().first()


# Session operations
async def get_or_create_session(db: AsyncSession, user_id: int) -> Session:
    result = await db.execute(select(Session).filter(Session.user_id == user_id))
    session = result.scalars().first()
    if not session:
        session = Session(user_id=user_id, conversation_history=json.dumps([]))
        db.add(session)
        await db.commit()
        await db.refresh(session)
    return session


async def update_session_history(db: AsyncSession, user_id: int, new_message: Dict[str, Any]) -> Session:
    session = await get_or_create_session(db, user_id)
    
    # Parse existing history
    history = json.loads(session.conversation_history)
    
    # Add new message
    history.append(new_message)
    
    # Keep only the last 10 messages
    if len(history) > 10:
        history = history[-10:]
    
    # Update session
    session.conversation_history = json.dumps(history)
    session.updated_at = datetime.now()
    await db.commit()
    await db.refresh(session)
    
    return session


async def get_session_history(db: AsyncSession, user_id: int) -> List[Dict[str, Any]]:
    session = await get_or_create_session(db, user_id)
    return json.loads(session.conversation_history)
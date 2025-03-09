import json
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from .models import User, Reminder, CalendarEvent, Session, RepeatFrequency


# User operations
def get_user_by_phone(db: Session, phone_number: str) -> Optional[User]:
    return db.query(User).filter(User.phone_number == phone_number).first()


def create_user(db: Session, phone_number: str) -> User:
    user = User(phone_number=phone_number)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_or_create_user(db: Session, phone_number: str) -> User:
    user = get_user_by_phone(db, phone_number)
    if not user:
        user = create_user(db, phone_number)
    
    # Update last active timestamp
    user.last_active = datetime.utcnow()
    db.commit()
    db.refresh(user)
    return user


# Reminder operations
def create_reminder(
    db: Session,
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
    db.commit()
    db.refresh(reminder)
    return reminder


def get_user_reminders(db: Session, user_id: int, active_only: bool = True) -> List[Reminder]:
    query = db.query(Reminder).filter(Reminder.user_id == user_id)
    if active_only:
        query = query.filter(Reminder.is_active == True)
    return query.order_by(Reminder.scheduled_time).all()


def get_upcoming_reminders(db: Session, user_id: int, days: int = 7) -> List[Reminder]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    return db.query(Reminder).filter(
        and_(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= now,
            Reminder.scheduled_time <= end_date,
            Reminder.is_active == True
        )
    ).order_by(Reminder.scheduled_time).all()


def get_due_reminders(db: Session) -> List[Reminder]:
    now = datetime.utcnow()
    return db.query(Reminder).filter(
        and_(
            Reminder.scheduled_time <= now,
            Reminder.is_active == True
        )
    ).all()


def update_reminder(db: Session, reminder_id: int, **kwargs) -> Optional[Reminder]:
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return None
    
    for key, value in kwargs.items():
        if hasattr(reminder, key):
            setattr(reminder, key, value)
    
    db.commit()
    db.refresh(reminder)
    return reminder


def delete_reminder(db: Session, reminder_id: int) -> bool:
    reminder = db.query(Reminder).filter(Reminder.id == reminder_id).first()
    if not reminder:
        return False
    
    reminder.is_active = False
    db.commit()
    return True


# Calendar event operations
def create_calendar_event(
    db: Session,
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
    db.commit()
    db.refresh(event)
    return event


def get_user_calendar_events(db: Session, user_id: int, active_only: bool = True) -> List[CalendarEvent]:
    query = db.query(CalendarEvent).filter(CalendarEvent.user_id == user_id)
    if active_only:
        query = query.filter(CalendarEvent.is_active == True)
    return query.order_by(CalendarEvent.start_time).all()


def get_upcoming_events(db: Session, user_id: int, days: int = 7) -> List[CalendarEvent]:
    now = datetime.utcnow()
    end_date = now + timedelta(days=days)
    return db.query(CalendarEvent).filter(
        and_(
            CalendarEvent.user_id == user_id,
            CalendarEvent.start_time >= now,
            CalendarEvent.start_time <= end_date,
            CalendarEvent.is_active == True
        )
    ).order_by(CalendarEvent.start_time).all()


def update_calendar_event(db: Session, event_id: int, **kwargs) -> Optional[CalendarEvent]:
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        return None
    
    for key, value in kwargs.items():
        if hasattr(event, key):
            setattr(event, key, value)
    
    db.commit()
    db.refresh(event)
    return event


def delete_calendar_event(db: Session, event_id: int) -> bool:
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        return False
    
    event.is_active = False
    db.commit()
    return True


def find_calendar_event_by_title(db: Session, user_id: int, title: str) -> Optional[CalendarEvent]:
    return db.query(CalendarEvent).filter(
        and_(
            CalendarEvent.user_id == user_id,
            CalendarEvent.title.ilike(f"%{title}%"),
            CalendarEvent.is_active == True
        )
    ).first()


# Session operations
def get_or_create_session(db: Session, user_id: int) -> Session:
    session = db.query(Session).filter(Session.user_id == user_id).first()
    if not session:
        session = Session(user_id=user_id, conversation_history=json.dumps([]))
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def update_session_history(db: Session, user_id: int, new_message: Dict[str, Any]) -> Session:
    session = get_or_create_session(db, user_id)
    
    # Parse existing history
    history = json.loads(session.conversation_history)
    
    # Add new message
    history.append(new_message)
    
    # Keep only the last 10 messages
    if len(history) > 10:
        history = history[-10:]
    
    # Update session
    session.conversation_history = json.dumps(history)
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    
    return session


def get_session_history(db: Session, user_id: int) -> List[Dict[str, Any]]:
    session = get_or_create_session(db, user_id)
    return json.loads(session.conversation_history)
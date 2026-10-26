"""Owner-scoped, in-app reminders. All stored instants are UTC."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .auth import current_owner
from .db import get_db
from .models import Application, Reminder, now

router = APIRouter(prefix="/api/reminders", tags=["reminders"])
Bucket = Literal["overdue", "due_today", "upcoming", "completed"]


class ReminderCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    application_id: UUID
    title: str = Field(min_length=1, max_length=200)
    due_at: AwareDatetime

    @field_validator("due_at")
    @classmethod
    def utc(cls, value):
        return value.astimezone(timezone.utc)


class ReminderPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_at: AwareDatetime | None = None
    completed: bool | None = None

    @field_validator("title", "due_at", "completed")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value.astimezone(timezone.utc) if isinstance(value, datetime) else value


class ReminderOut(BaseModel):
    id: UUID
    application_id: UUID
    title: str
    due_at: datetime
    completed_at: datetime | None
    created_at: datetime
    company_name: str
    job_title: str
    bucket: Bucket


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, "Unknown IANA timezone") from None


def classify(reminder, instant, tz):
    if reminder.completed_at is not None:
        return "completed"
    if reminder.due_at < instant:
        return "overdue"
    if reminder.due_at.astimezone(tz).date() == instant.astimezone(tz).date():
        return "due_today"
    return "upcoming"


def output(reminder, application, instant, tz):
    return ReminderOut(id=reminder.id, application_id=reminder.application_id,
        title=reminder.title, due_at=reminder.due_at, completed_at=reminder.completed_at,
        created_at=reminder.created_at, company_name=application.company_name,
        job_title=application.job_title, bucket=classify(reminder, instant, tz))


def owned_application(db, owner, id):
    item = db.scalar(select(Application).where(Application.id == id, Application.owner_id == owner))
    if item is None:
        raise HTTPException(404, "Application not found")
    return item


def owned_reminder(db, owner, id, lock=False):
    query = select(Reminder, Application).join(Application).where(Reminder.id == id, Application.owner_id == owner)
    if lock:
        query = query.with_for_update(of=Reminder)
    row = db.execute(query).first()
    if row is None:
        raise HTTPException(404, "Reminder not found")
    return row


@router.get("")
def listing(application_id: UUID | None = None, bucket: Bucket | None = None,
            timezone_name: str = Query("UTC", alias="timezone", max_length=100),
            page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=100),
            owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    tz, instant = zone(timezone_name), now()
    tomorrow = (instant.astimezone(tz) + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    query = select(Reminder, Application).join(Application).where(Application.owner_id == owner)
    if application_id:
        owned_application(db, owner, application_id)
        query = query.where(Reminder.application_id == application_id)
    category = case((Reminder.completed_at.is_not(None), "completed"),
                    (Reminder.due_at < instant, "overdue"),
                    (Reminder.due_at < tomorrow, "due_today"), else_="upcoming")
    counts_query = select(category, func.count()).select_from(Reminder).join(Application).where(Application.owner_id == owner)
    if application_id:
        counts_query = counts_query.where(Reminder.application_id == application_id)
    counts = dict(db.execute(counts_query.group_by(category)).all())
    if bucket:
        query = query.where(category == bucket)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.execute(query.order_by(Reminder.completed_at.is_not(None), Reminder.due_at, Reminder.id).offset((page - 1) * page_size).limit(page_size)).all()
    return {"items": [output(r, a, instant, tz) for r, a in rows], "total": total,
            "page": page, "page_size": page_size,
            "counts": {key: counts.get(key, 0) for key in ("overdue", "due_today", "upcoming", "completed")}}


@router.post("", response_model=ReminderOut, status_code=201)
def create(data: ReminderCreate, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    application = owned_application(db, owner, data.application_id)
    reminder = Reminder(**data.model_dump())
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return output(reminder, application, now(), ZoneInfo("UTC"))


@router.get("/{id}", response_model=ReminderOut)
def detail(id: UUID, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    reminder, application = owned_reminder(db, owner, id)
    return output(reminder, application, now(), ZoneInfo("UTC"))


@router.patch("/{id}", response_model=ReminderOut)
def update(id: UUID, data: ReminderPatch, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    reminder, application = owned_reminder(db, owner, id, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if "completed" in changes:
        completed = changes.pop("completed")
        reminder.completed_at = (reminder.completed_at or now()) if completed else None
    for key, value in changes.items():
        setattr(reminder, key, value)
    db.commit()
    db.refresh(reminder)
    return output(reminder, application, now(), ZoneInfo("UTC"))


@router.delete("/{id}", status_code=204)
def delete(id: UUID, owner: UUID = Depends(current_owner), db: Session = Depends(get_db)):
    reminder, _ = owned_reminder(db, owner, id, lock=True)
    db.delete(reminder)
    db.commit()

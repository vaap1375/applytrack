"""Gmail state, encrypted credentials, and minimal review/audit metadata."""
import uuid
from datetime import datetime
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON, Boolean, Integer, Float, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import now


class GmailConnection(Base):
    __tablename__ = 'gmail_connections'
    owner_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    encrypted_refresh: Mapped[str | None] = mapped_column(Text)
    health: Mapped[str] = mapped_column(String(40), default='connected')
    history_id: Mapped[str | None] = mapped_column(String(100))
    pending: Mapped[dict | None] = mapped_column(JSON)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dry_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auto_updates: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lookback_days: Mapped[int] = mapped_column(Integer, default=30)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class GmailOAuthState(Base):
    __tablename__ = 'gmail_oauth_states'
    owner_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    browser_hash: Mapped[str] = mapped_column(String(64))
    encrypted_verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GmailMatchRule(Base):
    __tablename__ = 'gmail_match_rules'
    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey('applications.id', ondelete='CASCADE'), primary_key=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    sender_domains: Mapped[list] = mapped_column(JSON, default=list)


class GmailMessage(Base):
    __tablename__ = 'gmail_messages'
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(index=True)
    gmail_id: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(300))
    sender: Mapped[str | None] = mapped_column(String(320))
    excerpt: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    classification: Mapped[str] = mapped_column(String(40))
    class_confidence: Mapped[float] = mapped_column(Float)
    match_confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    application_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('applications.id', ondelete='SET NULL'), index=True)
    proposed_status: Mapped[str | None] = mapped_column(String(20))
    old_status: Mapped[str | None] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(30), default='review', index=True)
    snapshot_revision: Mapped[int | None] = mapped_column(Integer)
    resulting_revision: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey('application_events.id', ondelete='SET NULL'))
    reason: Mapped[str] = mapped_column(String(500))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('owner_id', 'gmail_id', name='uq_gmail_owner_message'),)

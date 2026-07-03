"""Domain models (+db module)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)


class Submission(Base):
    __tablename__ = "submissions"

    console_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    coev2_job_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    last_seen_status: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_seen_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)

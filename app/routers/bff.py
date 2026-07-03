"""BFF routes for CoEv2 grade submissions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.coev2_client import CoEv2Client, CoEv2ClientError, get_coev2_client
from app.db import get_session
from app.models import Submission

router = APIRouter(prefix="/bff", tags=["bff"])
_DRAFTS: dict[str, dict[str, Any]] = {}


class GradeDraftIn(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class GradeConfirmIn(BaseModel):
    confirm_token: str
    idempotency_key: str


def prepare_grade(payload: dict[str, Any]) -> dict[str, Any]:
    confirm_token = str(uuid4())
    idempotency_key = str(uuid4())
    _DRAFTS[idempotency_key] = {
        "confirm_token": confirm_token,
        "payload": payload,
        "created_at": datetime.now(timezone.utc),
    }
    return {
        "confirm_token": confirm_token,
        "idempotency_key": idempotency_key,
        "spend_warning": "Submitting will call CoEv2 and may spend backend resources.",
        "cost": "unknown",
    }


def _extract_job_id(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("coev2_job_id", "job_id", "id"):
            value = data.get(key)
            if value is not None:
                return str(value)
    return str(uuid4())


def _extract_score(data: Any) -> float | None:
    if isinstance(data, dict):
        value = data.get("score")
        if isinstance(value, int | float):
            return float(value)
        for item in data.values():
            score = _extract_score(item)
            if score is not None:
                return score
    if isinstance(data, list):
        for item in data:
            score = _extract_score(item)
            if score is not None:
                return score
    return None


def _extract_status(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    value = data.get("status")
    return str(value) if value is not None else None


def confirm_grade(
    confirm_token: str,
    idempotency_key: str,
    session: Session,
    client: CoEv2Client,
) -> dict[str, Any]:
    existing = session.query(Submission).filter_by(idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        return {
            "duplicate": True,
            "console_id": existing.console_id,
            "coev2_job_id": existing.coev2_job_id,
            "kind": existing.kind,
        }

    draft = _DRAFTS.get(idempotency_key)
    if draft is None or draft["confirm_token"] != confirm_token:
        return {
            "error": "Confirmation required",
            "correlation_id": str(uuid4()),
        }

    try:
        data, correlation_id = client.grade(draft["payload"])
    except CoEv2ClientError as exc:
        return {
            "error": exc.message,
            "correlation_id": exc.correlation_id,
        }

    console_id = str(uuid4())
    coev2_job_id = _extract_job_id(data)
    submission = Submission(
        console_id=console_id,
        coev2_job_id=coev2_job_id,
        kind="grade",
        submitted_at=datetime.now(timezone.utc),
        last_seen_status=_extract_status(data),
        last_seen_score=_extract_score(data),
        idempotency_key=idempotency_key,
    )
    session.add(submission)
    session.commit()
    _DRAFTS.pop(idempotency_key, None)
    return {
        "duplicate": False,
        "console_id": console_id,
        "coev2_job_id": coev2_job_id,
        "kind": "grade",
        "correlation_id": correlation_id,
        "result": data,
    }


@router.post("/grade/prepare")
def prepare_grade_route(payload: GradeDraftIn):
    return prepare_grade(payload.payload)


@router.post("/grade/confirm")
def confirm_grade_route(
    payload: GradeConfirmIn,
    session: Session = Depends(get_session),
    client: CoEv2Client = Depends(get_coev2_client),
):
    return confirm_grade(payload.confirm_token, payload.idempotency_key, session, client)


@router.get("/submissions")
def list_submissions(session: Session = Depends(get_session)):
    submissions = (
        session.query(Submission).order_by(Submission.submitted_at.desc()).limit(20).all()
    )
    return [
        {
            "console_id": item.console_id,
            "coev2_job_id": item.coev2_job_id,
            "kind": item.kind,
            "submitted_at": item.submitted_at.isoformat(),
            "last_seen_status": item.last_seen_status,
            "last_seen_score": item.last_seen_score,
        }
        for item in submissions
    ]


@router.get("/submissions/{console_id}")
def get_submission(
    console_id: str,
    session: Session = Depends(get_session),
    client: CoEv2Client = Depends(get_coev2_client),
):
    submission = session.get(Submission, console_id)
    if submission is None:
        return {"error": "Submission not found", "correlation_id": str(uuid4())}
    try:
        data, correlation_id = client.get_job(submission.coev2_job_id)
        return {
            "console_id": submission.console_id,
            "coev2_job_id": submission.coev2_job_id,
            "kind": submission.kind,
            "correlation_id": correlation_id,
            "live": data,
        }
    except CoEv2ClientError as exc:
        return {"error": exc.message, "correlation_id": exc.correlation_id}

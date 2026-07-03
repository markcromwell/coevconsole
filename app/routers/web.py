"""Web UI (+ui module). Server-rendered Jinja pages."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.coev2_client import CoEv2Client, CoEv2ClientError, get_coev2_client
from app.db import get_session
from app.models import Submission
from app.routers.bff import confirm_grade, prepare_grade

router = APIRouter(tags=["web"])
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _history(session: Session) -> list[Submission]:
    return session.query(Submission).order_by(Submission.submitted_at.desc()).limit(20).all()


def _find_first(data: Any, names: set[str]) -> Any:
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in names:
                return value
        for value in data.values():
            found = _find_first(value, names)
            if found is not None:
                return found
    if isinstance(data, list):
        for value in data:
            found = _find_first(value, names)
            if found is not None:
                return found
    return None


def _view_model(result: Any) -> dict[str, Any]:
    if not result:
        return {"score": None, "findings": None, "cost": "unknown", "malformed": True}
    return {
        "score": _find_first(result, {"score", "grade_score"}),
        "findings": _find_first(result, {"findings", "issues", "comments"}),
        "cost": _find_first(result, {"cost", "total_cost", "reported_cost"}) or "unknown",
        "malformed": not isinstance(result, dict),
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request, session: Session = Depends(get_session)):
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": "CoEv2 Console",
            "history": _history(session),
            "state": "empty",
        },
    )


@router.get("/loading", response_class=HTMLResponse)
def loading(request: Request, session: Session = Depends(get_session)):
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": "CoEv2 Console",
            "history": _history(session),
            "state": "loading",
        },
    )


@router.post("/grade/prepare", response_class=HTMLResponse)
def prepare_grade_page(
    request: Request,
    prompt: str = Form(""),
    session: Session = Depends(get_session),
):
    draft = prepare_grade({"prompt": prompt})
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": "CoEv2 Console",
            "history": _history(session),
            "state": "confirm",
            "draft": draft,
            "prompt": prompt,
        },
    )


@router.post("/grade/confirm", response_class=HTMLResponse)
def confirm_grade_page(
    request: Request,
    confirm_token: str = Form(...),
    idempotency_key: str = Form(...),
    session: Session = Depends(get_session),
    client: CoEv2Client = Depends(get_coev2_client),
):
    response = confirm_grade(confirm_token, idempotency_key, session, client)
    result = response.get("result")
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": "CoEv2 Console",
            "history": _history(session),
            "state": "error" if response.get("error") else "result",
            "response": response,
            "result": result,
            "result_view": _view_model(result),
        },
    )


@router.get("/submissions/{console_id}", response_class=HTMLResponse)
def submission_page(
    request: Request,
    console_id: str,
    session: Session = Depends(get_session),
    client: CoEv2Client = Depends(get_coev2_client),
):
    submission = session.get(Submission, console_id)
    if submission is None:
        return RedirectResponse("/", status_code=303)
    try:
        result, correlation_id = client.get_job(submission.coev2_job_id)
        response = {
            "console_id": submission.console_id,
            "coev2_job_id": submission.coev2_job_id,
            "correlation_id": correlation_id,
            "result": result,
        }
        state = "result"
    except CoEv2ClientError as exc:
        result = None
        response = {"error": exc.message, "correlation_id": exc.correlation_id}
        state = "error"
    return _templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "app_name": "CoEv2 Console",
            "history": _history(session),
            "state": state,
            "response": response,
            "result": result,
            "result_view": _view_model(result),
        },
    )

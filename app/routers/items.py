"""Items CRUD (+db module example surface). Replace with real business endpoints.

The router carries Depends(require_api_key) so the whole CRUD surface is authenticated when APP_API_KEY is
configured (born-secure — see app/auth.py). Follow this pattern for new routers that mutate state."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import require_api_key
from app.db import get_session
from app.models import Item

router = APIRouter(prefix="/items", tags=["items"], dependencies=[Depends(require_api_key)])


class ItemIn(BaseModel):
    name: str


class ItemOut(BaseModel):
    id: int
    name: str
    model_config = {"from_attributes": True}


@router.get("", response_model=list[ItemOut])
def list_items(session: Session = Depends(get_session)):
    return session.query(Item).order_by(Item.id).all()


@router.post("", response_model=ItemOut, status_code=201)
def create_item(payload: ItemIn, session: Session = Depends(get_session)):
    item = Item(name=payload.name)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item

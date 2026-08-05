from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import DailyBrief, User
from app.schemas import BriefOut, MessageResponse, UnsubscribeRequest
from app.services import briefing
from app.utils.security import decode_unsubscribe_token

router = APIRouter(prefix="/briefs", tags=["briefs"])


@router.get("", response_model=list[BriefOut])
def list_briefs(
    limit: int = Query(30, le=90),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[DailyBrief]:
    return list(
        db.scalars(
            select(DailyBrief)
            .where(DailyBrief.user_id == user.id)
            .order_by(DailyBrief.brief_date.desc())
            .limit(limit)
        ).all()
    )


@router.get("/today", response_model=BriefOut)
def today(db: Session = Depends(get_db), user: User = Depends(current_user)) -> DailyBrief:
    """Generate on first read of the day, then serve from cache (Section 27)."""
    return briefing.generate_brief(db, user.id)


@router.post("/regenerate", response_model=BriefOut)
def regenerate(db: Session = Depends(get_db), user: User = Depends(current_user)) -> DailyBrief:
    return briefing.generate_brief(db, user.id, force=True)


@router.post("/unsubscribe", response_model=MessageResponse)
def unsubscribe(payload: UnsubscribeRequest, db: Session = Depends(get_db)) -> MessageResponse:
    """Turn off brief emails from the link in an email footer.

    POST rather than GET on purpose. Mail clients and security scanners
    routinely fetch every link in a message to preview or vet it, so a GET
    that mutates state would silently unsubscribe people who never clicked
    anything. The link in the email points at a frontend page; the page asks
    for a click; the click calls this.

    No auth beyond the signed token — someone reading their own email can't
    be expected to log in first, and the token can only ever disable email.
    """
    user_id = decode_unsubscribe_token(payload.token)
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")

    if user.email_briefs:
        user.email_briefs = False
        db.add(user)
        db.commit()
    return MessageResponse(message="You won't receive the daily brief by email any more.")


@router.get("/{brief_date}", response_model=BriefOut)
def get_brief(brief_date: date, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DailyBrief:
    brief = db.scalar(
        select(DailyBrief).where(DailyBrief.user_id == user.id, DailyBrief.brief_date == brief_date)
    )
    if brief is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No brief for {brief_date}")
    return brief

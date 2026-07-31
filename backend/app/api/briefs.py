from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db import get_db
from app.models import DailyBrief, User
from app.schemas import BriefOut
from app.services import briefing

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


@router.get("/{brief_date}", response_model=BriefOut)
def get_brief(brief_date: date, db: Session = Depends(get_db), user: User = Depends(current_user)) -> DailyBrief:
    brief = db.scalar(
        select(DailyBrief).where(DailyBrief.user_id == user.id, DailyBrief.brief_date == brief_date)
    )
    if brief is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No brief for {brief_date}")
    return brief

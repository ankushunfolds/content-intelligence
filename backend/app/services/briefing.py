"""Phase 6 — the AI Daily Brief (Section 13). The hero feature.

Order of operations matters and is enforced here:

  1. Python selects the signals and computes every number from the database.
  2. The LLM receives those finished numbers and writes the explanation.

The model is never asked what is trending, only why what we found matters
(Section 14). If the LLM is unavailable the brief still generates — it just
reads a little flatter.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, DailyBrief, TrackedChannel, Trend, Video, VideoIntelligence
from app.services.llm import UNTRUSTED_CONTENT_RULE, LLMError, MockLLM, _suggest_title, get_llm
from app.services.trends import compute_trends, top_trends
from app.utils.format import compact_number, multiplier, percent
from app.utils.logging import record_event
from app.utils.time import utcnow

SYSTEM_PROMPT = f"""You write a daily content-intelligence briefing for a YouTube creator.

You are given signals that have ALREADY been computed from a database. Your job is
to explain them, not to produce them.

Absolute rules:
- Never state a number that is not present in the input. Never round or embellish one.
- Every "why it matters" must cite the specific evidence given.
- Be concrete and plain. No hype, no "seems popular", no filler.
- Two sentences maximum per explanation.
- A suggested direction must be a specific, publishable video title that combines the
  topic with the format that is currently working.

Respond with JSON:
{{"headline": "<one sentence, what today is about>",
 "opportunities": [{{"id": <int>, "why_it_matters": "...", "suggested_direction": "..."}}],
 "competitor_highlights": [{{"id": <int>, "why_it_matters": "..."}}]}}

{UNTRUSTED_CONTENT_RULE}"""


def _competitor_channel_ids(db: Session, user_id: int, kind: str | None = None) -> list[int]:
    query = select(TrackedChannel.channel_id).where(TrackedChannel.user_id == user_id)
    if kind:
        query = query.where(TrackedChannel.type == kind)
    return list(db.scalars(query).all())


def select_opportunities(db: Session, user_id: int, limit: int) -> list[dict]:
    """Top trends, converted into opportunity records with evidence attached.

    A topic only becomes an *opportunity* if it is both accelerating and
    performing. Rising-but-underperforming topics are still reported under
    "rising trends" — they're information, not a recommendation.
    """
    candidates = [
        t
        for t in top_trends(db, user_id, limit * 3)
        if t.avg_performance >= settings.opportunity_min_performance
    ][:limit]

    opportunities = []
    for index, trend in enumerate(candidates):
        opportunities.append(
            {
                "id": index,
                "trend_id": trend.id,
                "topic": trend.topic,
                "subtopic": trend.subtopic,
                "momentum": trend.trend_score,
                "top_format": trend.top_format,
                "evidence": {
                    "window_days": trend.components.get("window_days", settings.trend_window_days),
                    "creator_count": trend.creator_count,
                    "video_count": trend.video_count,
                    "breakout_count": trend.breakout_count,
                    "volume_growth_pct": percent(trend.volume_growth),
                    "avg_performance": multiplier(trend.avg_performance),
                    "videos_per_day": round(trend.video_velocity, 2),
                },
                "score_breakdown": trend.components.get("signals", {}),
            }
        )
    return opportunities


def select_competitor_highlights(db: Session, user_id: int, limit: int) -> list[dict]:
    """Recent breakout videos from tracked competitors, best-performing first."""
    channel_ids = _competitor_channel_ids(db, user_id, "competitor") or _competitor_channel_ids(db, user_id)
    if not channel_ids:
        return []

    cutoff = utcnow() - timedelta(days=settings.trend_window_days * 2)
    rows = db.execute(
        select(Video, VideoIntelligence, Channel)
        .join(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .join(Channel, Channel.id == Video.channel_id)
        .where(Video.channel_id.in_(channel_ids))
        .where(Video.published_at >= cutoff)
        .where(VideoIntelligence.is_breakout.is_(True))
        .order_by(VideoIntelligence.performance_ratio.desc())
        .limit(limit)
    ).all()

    highlights = []
    for index, (video, intel, channel) in enumerate(rows):
        highlights.append(
            {
                "id": index,
                "video_id": video.id,
                "channel_name": channel.name,
                "channel_id": channel.id,
                "title": video.title,
                "url": video.url,
                "thumbnail_url": video.thumbnail_url,
                "views": video.views,
                "views_display": compact_number(video.views),
                "performance": multiplier(intel.performance_ratio),
                "performance_ratio": intel.performance_ratio,
                "baseline_display": compact_number(intel.baseline_views),
                "topic": intel.topic,
                "subtopic": intel.subtopic,
                "format": intel.format,
                "published_at": video.published_at.isoformat(),
            }
        )
    return highlights


def select_rising_trends(db: Session, user_id: int, limit: int) -> list[dict]:
    return [
        {
            "trend_id": trend.id,
            "topic": trend.topic,
            "subtopic": trend.subtopic,
            "score": trend.trend_score,
            "growth": percent(trend.volume_growth),
            "avg_performance": multiplier(trend.avg_performance),
            "creator_count": trend.creator_count,
            "video_count": trend.video_count,
            "top_format": trend.top_format,
        }
        for trend in top_trends(db, user_id, limit)
    ]


def _fallback_headline(opportunities: list[dict], highlights: list[dict], rising: list[dict] | None = None) -> str:
    if opportunities:
        top = opportunities[0]
        return (
            f"{top['subtopic'] or top['topic']} is the strongest signal in your niche today "
            f"at {top['momentum']}/100 momentum."
        )
    if highlights:
        return f"{highlights[0]['channel_name']} posted a {highlights[0]['performance']} breakout."
    if rising:
        # A trend exists but didn't clear the opportunity bar (Section 11: rising
        # volume without matching performance isn't a recommendation). Say that,
        # rather than claiming there's nothing here when the section below has data.
        top = rising[0]
        return (
            f"{top['subtopic'] or top['topic']} is gaining volume ({top['growth']}) but hasn't "
            f"cleared the performance bar yet — worth watching, not acting on."
        )
    return "Not enough signal yet — add a few more competitors or wait for the next ingestion run."


def _narrate(db: Session, payload: dict, user_id: int | None = None) -> tuple[dict, str]:
    """Hand the computed signals to the LLM for explanation. Degrades to mock on failure."""
    primary = get_llm()
    user_message = json.dumps({"brief": payload}, default=str)
    try:
        return (
            primary.complete_json(
                SYSTEM_PROMPT,
                user_message,
                model=settings.llm_brief_model,
                # Unlike classification, this one is worth thinking about: the
                # model has to weigh several competing signals and justify a
                # recommendation. -1 lets it spend what it needs.
                thinking_budget=settings.llm_brief_thinking_budget,
            ),
            primary.name,
        )
    except (LLMError, Exception) as exc:
        record_event(
            db,
            "llm.failure",
            f"brief narration fell back to mock: {exc}",
            level="error",
            status_code=getattr(exc, "status_code", None),
            stage="brief",
            # Without this there was no way to tell whose brief degraded, which
            # matters more here than for classification: a brief is cached for
            # the day, so the affected user stays degraded until it's cleared.
            user_id=user_id,
        )
        return MockLLM().complete_json(SYSTEM_PROMPT, user_message), "mock-fallback"


def generate_brief(db: Session, user_id: int, brief_date: date | None = None, force: bool = False) -> DailyBrief:
    """Build (or rebuild) today's brief. One per user per day."""
    brief_date = brief_date or utcnow().date()

    existing = db.scalar(
        select(DailyBrief).where(DailyBrief.user_id == user_id, DailyBrief.brief_date == brief_date)
    )
    if existing and not force:
        # The cache is only valid while it still describes what the user is
        # tracking. If they've removed every channel since this brief was
        # generated, serving it verbatim would show confident opportunities
        # and momentum scores for data that no longer exists on their account.
        # Regenerating costs nothing here — no channels means no LLM call.
        if _competitor_channel_ids(db, user_id):
            return existing
        compute_trends(db, user_id)  # also clears this user's now-orphaned trend rows
        force = True

    # --- 1. Python computes everything factual ---
    opportunities = select_opportunities(db, user_id, settings.max_brief_opportunities)
    highlights = select_competitor_highlights(db, user_id, settings.max_brief_highlights)
    rising = select_rising_trends(db, user_id, settings.max_brief_trends)

    payload = {
        "opportunities": opportunities,
        "competitor_highlights": highlights,
        "rising_trends": rising,
        "headline_fallback": _fallback_headline(opportunities, highlights, rising),
    }

    # --- 2. The LLM only writes prose over those numbers ---
    if opportunities or highlights:
        narration, source = _narrate(db, payload, user_id)
    else:
        narration, source = {}, "none"

    narrated_ops = {item.get("id"): item for item in narration.get("opportunities", [])}
    narrated_high = {item.get("id"): item for item in narration.get("competitor_highlights", [])}

    for opportunity in opportunities:
        written = narrated_ops.get(opportunity["id"], {})
        opportunity["why_it_matters"] = written.get("why_it_matters") or _evidence_sentence(opportunity)
        opportunity["suggested_direction"] = written.get("suggested_direction") or _suggest_title(
            opportunity["subtopic"] or opportunity["topic"], opportunity.get("top_format") or "Experiment"
        )

    for highlight in highlights:
        written = narrated_high.get(highlight["id"], {})
        highlight["why_it_matters"] = written.get("why_it_matters") or (
            f"{highlight['channel_name']} is at {highlight['performance']} their usual "
            f"{highlight['baseline_display']} views with a {(highlight['format'] or 'video').lower()} "
            f"on {highlight['subtopic'] or highlight['topic']}."
        )

    content = {
        "headline": narration.get("headline") or payload["headline_fallback"],
        "generated_at": utcnow().isoformat(),
        "opportunities": opportunities,
        "competitor_highlights": highlights,
        "rising_trends": rising,
        "stats": {
            "tracked_channels": len(_competitor_channel_ids(db, user_id)),
            "opportunities": len(opportunities),
            "breakouts": len(highlights),
            "trends": len(rising),
            "window_days": settings.trend_window_days,
        },
    }

    if existing:
        existing.content = content
        existing.generated_by = source
        brief = existing
        db.commit()
    else:
        brief = DailyBrief(user_id=user_id, brief_date=brief_date, content=content, generated_by=source)
        db.add(brief)
        try:
            db.commit()
        except IntegrityError:
            # Two requests both found no brief for today and both computed one
            # (e.g. two onboarding background tasks finishing at once). One
            # insert wins on (user_id, brief_date); take the other's result
            # rather than 500 on a request that did nothing wrong.
            db.rollback()
            brief = db.scalar(
                select(DailyBrief).where(DailyBrief.user_id == user_id, DailyBrief.brief_date == brief_date)
            )
            if brief is None:
                raise

    db.refresh(brief)
    record_event(
        db,
        "brief.generated",
        f"user {user_id} / {brief_date} via {source}",
        user_id=user_id,
        opportunities=len(opportunities),
        highlights=len(highlights),
    )
    return brief


def _evidence_sentence(opportunity: dict) -> str:
    """Deterministic fallback explanation — still evidence-first, just not prose-polished."""
    ev = opportunity["evidence"]
    return (
        f"{ev['creator_count']} tracked creators published {ev['video_count']} videos on "
        f"{opportunity['subtopic'] or opportunity['topic']} in the last {ev['window_days']} days "
        f"({ev['volume_growth_pct']} vs the prior window), averaging {ev['avg_performance']} "
        f"their creators' median views."
    )

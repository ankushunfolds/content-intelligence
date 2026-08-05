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
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, DailyBrief, TrackedChannel, Trend, Video, VideoIntelligence
from app.services.llm import UNTRUSTED_CONTENT_RULE, LLMError, MockLLM, _suggest_title, get_llm
from app.services.performance import channel_baseline
from app.services.trends import compute_trends, top_trends
from app.utils.format import compact_number, multiplier, percent
from app.utils.logging import logger, record_event
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


def own_channel_baseline(db: Session, user_id: int) -> int:
    """Median views on the user's *own* channel, or 0 if they haven't added one.

    This is what turns a niche-wide statistic into a personal one: "topics like
    this run 2.1x" is trivia, "expect roughly 25k" is a decision.
    """
    own_ids = _competitor_channel_ids(db, user_id, "own")
    if not own_ids:
        return 0
    channel = db.get(Channel, own_ids[0])
    return channel_baseline(db, channel) if channel is not None else 0


# A score built on three videos and one built on forty rendered identically
# before this, which quietly invites the same trust in both. These thresholds
# are judgement calls, not statistics — the point is to be visibly less
# confident when the sample is thin, not to imply a significance test.
def confidence_for(video_count: int, creator_count: int) -> dict:
    if video_count >= 12 and creator_count >= 4:
        return {
            "level": "solid",
            "note": f"{video_count} videos across {creator_count} creators.",
        }
    if video_count >= 6 and creator_count >= 2:
        return {
            "level": "moderate",
            "note": f"Only {video_count} videos across {creator_count} creators — directional.",
        }
    # Name the actual weakness. "Just 40 videos" is nonsense when the real
    # problem is that all 40 came from one channel — that isn't a thin sample,
    # it's a single creator's hobby horse, and the two need different wording
    # or the note undermines the number it's meant to qualify.
    if creator_count <= 1 and video_count >= 6:
        return {
            "level": "thin",
            "note": (
                f"All {video_count} videos come from a single creator — that's one channel's "
                "focus, not a trend across your niche."
            ),
        }
    creators = ""
    if creator_count:
        plural = "s" if creator_count != 1 else ""
        creators = f" from {creator_count} creator{plural}"
    return {
        "level": "thin",
        "note": f"Just {video_count} videos{creators} — treat as a hint, not a finding.",
    }


def own_channel_topics(db: Session, user_id: int, days: int = 90) -> set[str]:
    """Subtopics the user has published on themselves, lower-cased.

    Used to separate "this is working in your niche" from "this is working in
    your niche and you have never touched it" — the second is a materially
    stronger recommendation, and the data to tell them apart was already here.
    """
    own_ids = _competitor_channel_ids(db, user_id, "own")
    if not own_ids:
        return set()

    cutoff = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(VideoIntelligence.subtopic)
        .join(Video, Video.id == VideoIntelligence.video_id)
        .where(Video.channel_id.in_(own_ids))
        .where(Video.published_at >= cutoff)
        .where(VideoIntelligence.subtopic.is_not(None))
    ).all()
    return {row[0].strip().lower() for row in rows if row[0]}


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

    baseline = own_channel_baseline(db, user_id)
    covered = own_channel_topics(db, user_id)
    # An empty set means we have no idea what they cover — no own channel, or
    # nothing classified yet — not that they've covered nothing. Without this
    # every single topic gets flagged as a gap, which is a confident claim
    # built on missing data.
    gaps_knowable = bool(covered)

    opportunities = []
    for index, trend in enumerate(candidates):
        # Projected onto the user's own median rather than reported as an
        # abstract multiple. Deliberately arithmetic, not a forecast: it says
        # "a topic performing like this, on a channel your size" — no model
        # is involved and none should be.
        expected_views = int(baseline * trend.avg_performance) if baseline else 0

        opportunities.append(
            {
                "id": index,
                "trend_id": trend.id,
                "topic": trend.topic,
                "subtopic": trend.subtopic,
                "momentum": trend.trend_score,
                "top_format": trend.top_format,
                "confidence": confidence_for(trend.video_count, trend.creator_count),
                "saturation": trend.components.get("saturation") or {"level": "open", "note": ""},
                "formats": trend.components.get("formats") or [],
                # "Six competitors covered this, you never have" is a stronger
                # recommendation than the same topic you already post about —
                # but only claim it when we actually know what they cover.
                "is_gap": gaps_knowable
                and (trend.subtopic or trend.topic).strip().lower() not in covered,
                "projection": {
                    "your_baseline": baseline,
                    "your_baseline_display": compact_number(baseline) if baseline else None,
                    "expected_views": expected_views,
                    "expected_views_display": compact_number(expected_views) if expected_views else None,
                },
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


def _fallback_headline(
    opportunities: list[dict],
    highlights: list[dict],
    rising: list[dict] | None = None,
    has_channels: bool = True,
) -> str:
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
    # Two different silences, and telling a user the wrong one is worse than
    # saying nothing. With no channels tracked there is no niche to be quiet —
    # that's an unfinished setup, and "stick to your plan" would be nonsense.
    if not has_channels:
        return "Not enough signal yet — add a few competitors to start tracking your niche."
    # With channels tracked, nothing clearing the bar is a real finding.
    return "Quiet day in your niche — nothing cleared the bar. Stick to your plan."


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
            # Non-HTTP failures (malformed JSON in a 200 body) have no status.
            # Without this they'd be missing from errors_by_status entirely.
            failure_reason=getattr(exc, "reason", None),
            stage="brief",
            # Without this there was no way to tell whose brief degraded, which
            # matters more here than for classification: a brief is cached for
            # the day, so the affected user stays degraded until it's cleared.
            user_id=user_id,
        )
        return MockLLM().complete_json(SYSTEM_PROMPT, user_message), "mock-fallback"


# Sources that mean "the prose in this brief is template output, not analysis".
FALLBACK_SOURCES = {"mock", "mock-fallback"}


def _degraded_retry_due(brief: DailyBrief) -> bool:
    """Should we try again on a brief that came out as template text?

    Briefs are cached one per user per day, which is right for cost but means a
    momentary provider failure is served for up to 24 hours. On 3 Aug a single
    503 — the kind that clears in seconds — left a user reading template text
    for the rest of the day. Retrying on read fixes that without a scheduler.

    The cooldown is what makes it safe. Without it, a sustained outage would
    fire an LLM call on every page load: slowest and most expensive exactly
    when the provider is already struggling. With it, each user costs at most
    one attempt per interval, and recovery still happens within minutes.
    """
    if brief.generated_by not in FALLBACK_SOURCES:
        return False
    if not settings.using_real_llm:
        return False  # mock is the intended provider here; retrying loops forever

    content = brief.content if isinstance(brief.content, dict) else {}
    stamp = content.get("generated_at")
    if not stamp:
        return True
    try:
        generated_at = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return True
    return utcnow() - generated_at >= timedelta(minutes=settings.brief_degraded_retry_minutes)


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
        if not _competitor_channel_ids(db, user_id):
            compute_trends(db, user_id)  # also clears this user's now-orphaned trend rows
            force = True
        elif _degraded_retry_due(existing):
            # Same principle, different defect: this brief is cached but it is
            # template text, not analysis. Serving it for the rest of the day
            # because a provider blinked once is not a cache hit worth having.
            logger.info("brief for user %s is %s — retrying narration", user_id, existing.generated_by)
            force = True
        else:
            return existing

    # --- 1. Python computes everything factual ---
    opportunities = select_opportunities(db, user_id, settings.max_brief_opportunities)
    highlights = select_competitor_highlights(db, user_id, settings.max_brief_highlights)
    rising = select_rising_trends(db, user_id, settings.max_brief_trends)

    tracked_channel_ids = _competitor_channel_ids(db, user_id)

    payload = {
        "opportunities": opportunities,
        "competitor_highlights": highlights,
        "rising_trends": rising,
        "headline_fallback": _fallback_headline(
            opportunities, highlights, rising, has_channels=bool(tracked_channel_ids)
        ),
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
        # A day with nothing worth acting on is a real answer, not an empty
        # page. Most tools in this category manufacture five ideas daily
        # whether or not five exist, which trains people to ignore all of
        # them. Saying "quiet week" is what makes a loud day mean something —
        # and it's also the flag that suppresses the daily email.
        # Only a *quiet* day if there was somewhere for signal to come from.
        # An account with no channels isn't quiet, it's unfinished — and it
        # must not suppress email on the grounds of a calm niche.
        "quiet_day": bool(tracked_channel_ids) and not opportunities,
        "opportunities": opportunities,
        "competitor_highlights": highlights,
        "rising_trends": rising,
        "stats": {
            "tracked_channels": len(tracked_channel_ids),
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


def _plural(count: int, noun: str) -> str:
    """"1 creators published 1 videos" appeared verbatim in production whenever
    the LLM degraded to this fallback. Small, but it's the sentence a user
    reads on exactly the days the product is already underperforming."""
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _evidence_sentence(opportunity: dict) -> str:
    """Deterministic fallback explanation — still evidence-first, just not prose-polished."""
    ev = opportunity["evidence"]
    creators = _plural(ev["creator_count"], "tracked creator")
    videos = _plural(ev["video_count"], "video")
    return (
        f"{creators} published {videos} on "
        f"{opportunity['subtopic'] or opportunity['topic']} in the last {ev['window_days']} days "
        f"({ev['volume_growth_pct']} vs the prior window), averaging {ev['avg_performance']} "
        f"their creators' median views."
    )

"""Phase 4 — topic / subtopic / format / angle for each video (Section 10).

Cost control (Section 27): classify each video exactly once, in batches, using
only the title, tags and a description snippet. Never on page load.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Channel, Video, VideoIntelligence
from app.services.llm import UNTRUSTED_CONTENT_RULE, LLMError, MockLLM, get_llm
from app.utils.logging import record_event
from app.utils.time import utcnow

BATCH_SIZE = 20

SYSTEM_PROMPT = f"""You classify YouTube videos for a content intelligence system.

For each video return:
  topic     - broad category, 1-2 words, reused consistently (e.g. "AI", "Business")
  subtopic  - the specific thing covered, 1-3 words (e.g. "AI Agents", "Monetization")
  format    - one of: Experiment, Tutorial, Listicle, Review, Case Study, Commentary, Interview
  angle     - the specific take, under 12 words

Consistency across videos matters more than nuance: prefer an existing label over
inventing a near-duplicate.

Respond with JSON using these exact short keys, one object per video:
{{"r":[{{"i":<int>,"t":"<topic>","s":"<subtopic>","f":"<format>","a":"<angle>"}}]}}

Keys are abbreviated deliberately — at 20 videos per call the full key names
cost more output tokens than several of the values do. Emit no other keys, no
prose, and no explanation.

{UNTRUSTED_CONTENT_RULE}"""


def _pending_videos(db: Session, channel_ids: list[int], limit: int | None = None) -> list[Video]:
    """Videos with no classification yet. Already-classified videos are never re-sent."""
    query = (
        select(Video)
        .outerjoin(VideoIntelligence, VideoIntelligence.video_id == Video.id)
        .where(Video.channel_id.in_(channel_ids))
        .where((VideoIntelligence.id.is_(None)) | (VideoIntelligence.topic.is_(None)))
        .order_by(Video.published_at.desc())
    )
    if limit:
        query = query.limit(limit)
    return list(db.scalars(query).all())


# The title carries almost all of the classification signal; the description is
# a tiebreaker for vague titles. 280 chars of it was mostly channel boilerplate
# — subscribe links, affiliate blocks, chapter lists — which is both wasted
# spend and extra surface for prompt injection.
DESCRIPTION_CHARS = 160


def _payload(videos: list[Video]) -> str:
    # `tags` used to be sent here as a hardcoded empty list for every video —
    # ingestion never populated it. That was pure token waste, so it's gone.
    # If tags ever do get ingested, add the field back with real values.
    return json.dumps(
        {
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "description": (v.description or "")[:DESCRIPTION_CHARS],
                }
                for v in videos
            ]
        },
        separators=(",", ":"),  # no whitespace: it is billed like any other token
    )


def _field(row: dict, *names: str) -> Any:
    """First present key out of `names`.

    The Gemini prompt asks for short keys to save output tokens; MockLLM and the
    OpenAI path emit the long ones. Rather than force one schema on every
    provider, read both — the alternative is a fallback that silently applies
    nothing because the keys didn't match.
    """
    for name in names:
        value = row.get(name)
        if value is not None:
            return value
    return None


def _apply(db: Session, videos: list[Video], results: list[dict], source: str) -> int:
    by_id = {v.id: v for v in videos}
    applied = 0
    for row in results:
        video = by_id.get(_field(row, "i", "id"))
        if video is None:
            continue
        intel = video.intelligence
        if intel is None:
            intel = VideoIntelligence(video_id=video.id)
            db.add(intel)
            db.flush()
            video.intelligence = intel
        intel.topic = (_field(row, "t", "topic") or "General").strip()[:120]
        intel.subtopic = (_field(row, "s", "subtopic") or intel.topic).strip()[:120]
        intel.format = (_field(row, "f", "format") or "Commentary").strip()[:60]
        intel.angle = (_field(row, "a", "angle") or video.title).strip()[:255]
        intel.classified_by = source
        intel.classified_at = utcnow()
        intel.updated_at = utcnow()
        applied += 1
    return applied


def classify_videos(db: Session, videos: list[Video]) -> int:
    if not videos:
        return 0

    primary = get_llm()
    fallback = MockLLM()
    classified = 0

    for start in range(0, len(videos), BATCH_SIZE):
        batch = videos[start : start + BATCH_SIZE]
        payload = _payload(batch)
        client, source = primary, primary.name
        try:
            response = client.complete_json(
                SYSTEM_PROMPT,
                payload,
                # Assigning a topic and one of seven format labels is pattern
                # matching, not reasoning. Paying output-rate tokens to think
                # about it buys nothing.
                thinking_budget=settings.llm_classify_thinking_budget,
            )
        except (LLMError, Exception) as exc:  # degrade rather than fail the pipeline
            record_event(db, "llm.failure", f"classification fell back to mock: {exc}", level="error")
            response = fallback.complete_json(SYSTEM_PROMPT, payload)
            source = "mock-fallback"

        classified += _apply(db, batch, _field(response, "r", "results") or [], source)
        db.commit()

    record_event(db, "classification.run", f"classified {classified} videos", videos=classified)
    return classified


def classify_pending(db: Session, channels: list[Channel], limit: int | None = None) -> int:
    """Classify everything not yet classified for these channels."""
    if not channels:
        return 0
    return classify_videos(db, _pending_videos(db, [c.id for c in channels], limit))

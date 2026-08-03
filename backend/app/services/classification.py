"""Phase 4 — topic / subtopic / format / angle for each video (Section 10).

Cost control (Section 27): classify each video exactly once, in batches, using
only the title, tags and a description snippet. Never on page load.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

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
inventing a near-duplicate. Respond with JSON: {{"results":[{{"id":<int>,"topic":...,
"subtopic":...,"format":...,"angle":...}}]}}

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


def _payload(videos: list[Video]) -> str:
    return json.dumps(
        {
            "videos": [
                {
                    "id": v.id,
                    "title": v.title,
                    "tags": [],
                    "description": (v.description or "")[:280],
                }
                for v in videos
            ]
        }
    )


def _apply(db: Session, videos: list[Video], results: list[dict], source: str) -> int:
    by_id = {v.id: v for v in videos}
    applied = 0
    for row in results:
        video = by_id.get(row.get("id"))
        if video is None:
            continue
        intel = video.intelligence
        if intel is None:
            intel = VideoIntelligence(video_id=video.id)
            db.add(intel)
            db.flush()
            video.intelligence = intel
        intel.topic = (row.get("topic") or "General").strip()[:120]
        intel.subtopic = (row.get("subtopic") or intel.topic).strip()[:120]
        intel.format = (row.get("format") or "Commentary").strip()[:60]
        intel.angle = (row.get("angle") or video.title).strip()[:255]
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
            response = client.complete_json(SYSTEM_PROMPT, payload)
        except (LLMError, Exception) as exc:  # degrade rather than fail the pipeline
            record_event(db, "llm.failure", f"classification fell back to mock: {exc}", level="error")
            response = fallback.complete_json(SYSTEM_PROMPT, payload)
            source = "mock-fallback"

        classified += _apply(db, batch, response.get("results", []), source)
        db.commit()

    record_event(db, "classification.run", f"classified {classified} videos", videos=classified)
    return classified


def classify_pending(db: Session, channels: list[Channel], limit: int | None = None) -> int:
    """Classify everything not yet classified for these channels."""
    if not channels:
        return 0
    return classify_videos(db, _pending_videos(db, [c.id for c in channels], limit))

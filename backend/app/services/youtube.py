"""YouTube data access.

Two providers behind one interface:

  * ``RealYouTubeProvider`` — YouTube Data API v3.
  * ``MockYouTubeProvider`` — deterministic synthetic data so the whole system
    runs, and can be demoed, with no API key.

Both return the same plain dataclasses, so nothing downstream knows the difference.
"""
from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol

import httpx

from app.config import settings
from app.utils.logging import logger
from app.utils.time import parse_iso, parse_iso_duration, utcnow

API_ROOT = "https://www.googleapis.com/youtube/v3"


class ChannelNotFound(Exception):
    pass


class ProviderError(Exception):
    pass


@dataclass
class ChannelData:
    youtube_channel_id: str
    name: str
    handle: str | None
    url: str
    thumbnail_url: str | None
    subscriber_count: int
    total_views: int
    video_count: int
    uploads_playlist_id: str | None = None


@dataclass
class VideoData:
    youtube_video_id: str
    title: str
    description: str
    published_at: object  # datetime
    views: int
    likes: int
    comments: int
    duration_seconds: int
    thumbnail_url: str | None
    url: str
    tags: list[str] = field(default_factory=list)


class YouTubeProvider(Protocol):
    def resolve_channel(self, identifier: str) -> ChannelData: ...
    def fetch_videos(self, channel: ChannelData, limit: int) -> list[VideoData]: ...


# ---------------------------------------------------------------------------
# Identifier parsing
# ---------------------------------------------------------------------------

_HANDLE_RE = re.compile(r"@([A-Za-z0-9._\-]+)")
_CHANNEL_ID_RE = re.compile(r"(UC[A-Za-z0-9_\-]{22})")
_CUSTOM_RE = re.compile(r"youtube\.com/(?:c|user)/([A-Za-z0-9._\-]+)")


def parse_identifier(raw: str) -> tuple[str, str]:
    """Classify a user-supplied channel reference.

    Returns ``(kind, value)`` where kind is ``id`` | ``handle`` | ``search``.
    """
    value = (raw or "").strip()
    if not value:
        raise ChannelNotFound("Empty channel identifier")

    if match := _CHANNEL_ID_RE.search(value):
        return "id", match.group(1)
    if match := _CUSTOM_RE.search(value):
        return "search", match.group(1)
    if match := _HANDLE_RE.search(value):
        return "handle", match.group(1)
    if "youtube.com" in value or "youtu.be" in value:
        tail = value.rstrip("/").split("/")[-1]
        return "search", tail
    return "search", value


# ---------------------------------------------------------------------------
# Real provider
# ---------------------------------------------------------------------------


# YouTube Data API v3 charges per call, and wildly unevenly: the free tier is
# 10,000 units/day and a single search costs 100 of them. Onboarding 50 users
# whose channel URLs all need searching would spend ~46,000 units — over four
# times the daily allowance — while the same 50 users onboarded via @handles
# would spend under 2,000. Same product, 25x the quota, decided entirely by
# what someone pasted into a form field.
#
# Tracked so that quota exhaustion shows up as a number in the event log,
# rather than as onboarding mysteriously failing with a 403 one afternoon.
QUOTA_UNITS = {"search": 100}
DEFAULT_QUOTA_UNITS = 1


class RealYouTubeProvider:
    def __init__(self, api_key: str, timeout: float = 20.0) -> None:
        if not api_key:
            raise ProviderError("YOUTUBE_API_KEY is required for the youtube provider")
        self.api_key = api_key
        self.timeout = timeout
        self.units_used = 0

    def _get(self, path: str, **params) -> dict:
        self.units_used += QUOTA_UNITS.get(path, DEFAULT_QUOTA_UNITS)
        params["key"] = self.api_key
        try:
            response = httpx.get(f"{API_ROOT}/{path}", params=params, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ProviderError(f"YouTube API request failed: {exc}") from exc
        if response.status_code == 403:
            raise ProviderError("YouTube API quota exceeded or key rejected (403)")
        if response.status_code >= 400:
            raise ProviderError(f"YouTube API error {response.status_code}: {response.text[:300]}")
        return response.json()

    def resolve_channel(self, identifier: str) -> ChannelData:
        kind, value = parse_identifier(identifier)

        if kind == "id":
            payload = self._get("channels", part="snippet,statistics,contentDetails", id=value)
        elif kind == "handle":
            payload = self._get("channels", part="snippet,statistics,contentDetails", forHandle=f"@{value}")
        else:
            # A custom URL slug (/c/Name) or a bare name is very often also the
            # channel's @handle. forHandle costs 1 unit and search costs 100, so
            # guessing first is worth it at 100:1 odds: a wrong guess wastes one
            # unit, a right one saves ninety-nine. It also seeds `handle` in the
            # database, which lets the next user tracking the same channel skip
            # the lookup entirely.
            payload = {}
            try:
                payload = self._get(
                    "channels", part="snippet,statistics,contentDetails", forHandle=f"@{value}"
                )
            except ProviderError:
                payload = {}  # a failed guess must not fail the resolution

            if not (payload.get("items") or []):
                search = self._get("search", part="snippet", q=value, type="channel", maxResults=1)
                items = search.get("items") or []
                if not items:
                    raise ChannelNotFound(f"No YouTube channel matched '{identifier}'")
                channel_id = items[0]["snippet"]["channelId"]
                payload = self._get("channels", part="snippet,statistics,contentDetails", id=channel_id)

        items = payload.get("items") or []
        if not items:
            raise ChannelNotFound(f"No YouTube channel matched '{identifier}'")

        item = items[0]
        snippet = item["snippet"]
        stats = item.get("statistics", {})
        custom_url = snippet.get("customUrl") or ""
        return ChannelData(
            youtube_channel_id=item["id"],
            name=snippet.get("title", "Unknown channel"),
            handle=custom_url.lstrip("@") or None,
            url=f"https://www.youtube.com/channel/{item['id']}",
            thumbnail_url=(snippet.get("thumbnails", {}).get("high") or {}).get("url"),
            subscriber_count=int(stats.get("subscriberCount", 0) or 0),
            total_views=int(stats.get("viewCount", 0) or 0),
            video_count=int(stats.get("videoCount", 0) or 0),
            uploads_playlist_id=item.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
        )

    def fetch_videos(self, channel: ChannelData, limit: int) -> list[VideoData]:
        playlist_id = channel.uploads_playlist_id
        if not playlist_id:
            refreshed = self.resolve_channel(channel.youtube_channel_id)
            playlist_id = refreshed.uploads_playlist_id
        if not playlist_id:
            return []

        video_ids: list[str] = []
        page_token: str | None = None
        while len(video_ids) < limit:
            payload = self._get(
                "playlistItems",
                part="contentDetails",
                playlistId=playlist_id,
                maxResults=min(50, limit - len(video_ids)),
                **({"pageToken": page_token} if page_token else {}),
            )
            for item in payload.get("items", []):
                vid = item.get("contentDetails", {}).get("videoId")
                if vid:
                    video_ids.append(vid)
            page_token = payload.get("nextPageToken")
            if not page_token:
                break

        videos: list[VideoData] = []
        # videos.list accepts 50 ids per call — batch to keep quota cost low.
        for start in range(0, len(video_ids), 50):
            batch = video_ids[start : start + 50]
            payload = self._get("videos", part="snippet,statistics,contentDetails", id=",".join(batch))
            for item in payload.get("items", []):
                snippet = item["snippet"]
                stats = item.get("statistics", {})
                thumbs = snippet.get("thumbnails", {})
                videos.append(
                    VideoData(
                        youtube_video_id=item["id"],
                        title=snippet.get("title", ""),
                        description=(snippet.get("description") or "")[:5000],
                        published_at=parse_iso(snippet["publishedAt"]),
                        views=int(stats.get("viewCount", 0) or 0),
                        likes=int(stats.get("likeCount", 0) or 0),
                        comments=int(stats.get("commentCount", 0) or 0),
                        duration_seconds=parse_iso_duration(item.get("contentDetails", {}).get("duration", "")),
                        thumbnail_url=(thumbs.get("high") or thumbs.get("medium") or {}).get("url"),
                        url=f"https://www.youtube.com/watch?v={item['id']}",
                        tags=snippet.get("tags", []) or [],
                    )
                )
        return videos


# ---------------------------------------------------------------------------
# Mock provider — deterministic, realistic, key-free
# ---------------------------------------------------------------------------

# Each entry: (topic, subtopic, momentum) where momentum > 1 means the topic is
# genuinely accelerating in the recent window — this is what the trend engine
# should discover on its own, not something it is told.
_TOPIC_LIBRARY: list[tuple[str, str, float]] = [
    ("AI", "AI Agents", 2.6),
    ("AI", "AI Video Tools", 1.9),
    ("AI", "Prompt Engineering", 0.8),
    ("AI", "Local LLMs", 1.4),
    ("Creator Economy", "Creator Automation", 2.1),
    ("Creator Economy", "Monetization", 0.9),
    ("Creator Economy", "Audience Growth", 1.0),
    ("Productivity", "Note Taking", 0.7),
    ("Productivity", "Workflow Systems", 1.1),
    ("Business", "Solo Founders", 1.3),
    ("Business", "SaaS Teardowns", 0.9),
    ("Technology", "Hardware Reviews", 0.8),
]

_FORMATS = ["Experiment", "Tutorial", "Listicle", "Review", "Case Study", "Commentary", "Interview"]

_TITLE_TEMPLATES = {
    "Experiment": ["I Tested {sub} for 30 Days", "I Used {sub} Every Day for a Week"],
    "Tutorial": ["How to Use {sub} (Complete Guide)", "{sub}: The Setup I Actually Use"],
    "Listicle": ["{n} {sub} Tools That Changed My Workflow", "Top {n} {sub} Ideas for 2026"],
    "Review": ["{sub} Honest Review After 3 Months", "Is {sub} Actually Worth It?"],
    "Case Study": ["How I Grew Using {sub}", "{sub}: What Worked and What Didn't"],
    "Commentary": ["Why Everyone Is Wrong About {sub}", "The Truth About {sub}"],
    "Interview": ["A Creator Explains {sub}", "Talking {sub} With a Full-Time Creator"],
}

_CHANNEL_NAMES = [
    "Signal Studio", "The Build Log", "Creator Lab", "Deep Work Media", "Practical AI",
    "Growth Notes", "The Leverage Show", "Output Channel", "Make It Ship", "North Loop",
]


class MockYouTubeProvider:
    """Synthetic YouTube. Same identifier always yields the same channel and videos."""

    units_used = 0  # no API, no quota — present so callers need not special-case

    def _seed(self, key: str) -> int:
        return int(hashlib.sha256(key.encode()).hexdigest()[:12], 16)

    def resolve_channel(self, identifier: str) -> ChannelData:
        kind, value = parse_identifier(identifier)
        rng = random.Random(self._seed(value.lower()))

        readable = value.replace("-", " ").replace("_", " ").strip()
        name = readable.title() if len(readable) > 2 else rng.choice(_CHANNEL_NAMES)
        channel_id = "UC" + hashlib.sha256(value.lower().encode()).hexdigest()[:22]
        subscribers = int(rng.choice([12_000, 34_000, 78_000, 142_000, 310_000, 480_000]) * rng.uniform(0.85, 1.15))
        video_count = rng.randint(120, 640)

        return ChannelData(
            youtube_channel_id=channel_id,
            name=name,
            handle=re.sub(r"[^A-Za-z0-9]", "", value.lower())[:24] or None,
            url=f"https://www.youtube.com/channel/{channel_id}",
            thumbnail_url=None,
            subscriber_count=subscribers,
            total_views=subscribers * rng.randint(40, 120),
            video_count=video_count,
            uploads_playlist_id=f"UU{channel_id[2:]}",
        )

    def fetch_videos(self, channel: ChannelData, limit: int) -> list[VideoData]:
        rng = random.Random(self._seed(channel.youtube_channel_id))
        now = utcnow()

        # Channel baseline scales with audience size, with per-channel variance.
        baseline = max(2_000, int(channel.subscriber_count * rng.uniform(0.08, 0.35)))
        cadence_days = rng.choice([2, 2, 3, 3, 4, 5])

        # Competitors in a niche cover overlapping ground, so every channel gets
        # some of the accelerating topics plus a couple of its own. Without this
        # overlap the trend engine sees scattered one-off videos, not a trend.
        rising = sorted(_TOPIC_LIBRARY, key=lambda t: t[2], reverse=True)[:4]
        others = [t for t in _TOPIC_LIBRARY if t not in rising]
        topics = rng.sample(rising, k=3) + rng.sample(others, k=2)
        signature_format = rng.choice(_FORMATS)

        videos: list[VideoData] = []
        for index in range(limit):
            age_days = index * cadence_days + rng.randint(0, 1)
            published = now - timedelta(days=age_days, hours=rng.randint(0, 23))
            recent = age_days <= settings.trend_window_days

            # Rising topics appear disproportionately often in the recent window —
            # squared, so the concentration is strong enough for the trend engine
            # to find something real rather than noise.
            weights = [(t[2] ** 2 if recent else 1.0) for t in topics]
            topic, subtopic, momentum = rng.choices(topics, weights=weights, k=1)[0]

            fmt = signature_format if rng.random() < 0.45 else rng.choice(_FORMATS)
            template = rng.choice(_TITLE_TEMPLATES[fmt])
            title = template.format(sub=subtopic, n=rng.choice([3, 5, 7, 10]))

            # Views: baseline, dampened by video age (older videos accumulated more,
            # newer ones are still climbing), lifted where the topic has real momentum.
            maturity = min(1.0, 0.35 + age_days / 14)
            multiplier = rng.lognormvariate(0.0, 0.45)
            if recent and momentum > 1.5 and rng.random() < 0.35:
                multiplier *= rng.uniform(2.4, 4.6)  # a genuine breakout
            views = max(300, int(baseline * maturity * multiplier * (momentum ** 0.35)))

            engagement = rng.uniform(0.025, 0.06)
            video_id = hashlib.sha256(f"{channel.youtube_channel_id}:{index}".encode()).hexdigest()[:11]
            videos.append(
                VideoData(
                    youtube_video_id=video_id,
                    title=title,
                    description=f"In this video we cover {subtopic.lower()} — a {fmt.lower()} on {topic.lower()}.",
                    published_at=published,
                    views=views,
                    likes=int(views * engagement),
                    comments=int(views * engagement * rng.uniform(0.04, 0.12)),
                    duration_seconds=rng.randint(300, 1800),
                    thumbnail_url=None,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    tags=[topic, subtopic, fmt],
                )
            )
        return videos


def get_provider() -> YouTubeProvider:
    if settings.youtube_provider == "youtube":
        if not settings.youtube_api_key:
            logger.warning("YOUTUBE_PROVIDER=youtube but no API key set — falling back to mock data")
            return MockYouTubeProvider()
        return RealYouTubeProvider(settings.youtube_api_key)
    return MockYouTubeProvider()

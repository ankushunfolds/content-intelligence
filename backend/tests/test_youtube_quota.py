"""YouTube Data API quota is the real 50-user ceiling, not the LLM bill.

Free tier is 10,000 units/day. A channel search costs 100 units; every other
call in this codebase costs 1. Fifty users onboarding ~9 channels each spend
~1,800 units if those channels resolve by handle and ~46,000 if they resolve
by search — the same product, 25x the quota, decided by what someone pasted
into a form field.
"""
from __future__ import annotations

import pytest

from app.models import Channel
from app.services import ingestion
from app.services.youtube import (
    DEFAULT_QUOTA_UNITS,
    QUOTA_UNITS,
    ChannelData,
    RealYouTubeProvider,
    parse_identifier,
)


class _FakeProvider:
    """Counts resolutions so cache hits are observable."""

    units_used = 0

    def __init__(self) -> None:
        self.calls: list[str] = []

    def resolve_channel(self, identifier: str) -> ChannelData:
        self.calls.append(identifier)
        return ChannelData(
            youtube_channel_id="UC" + "x" * 22,
            name="Fresh Channel",
            handle="freshchannel",
            url="https://youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx",
            thumbnail_url=None,
            subscriber_count=100,
            total_views=1000,
            video_count=10,
        )


def _store(db, *, channel_id: str, handle: str | None, name: str = "Cached") -> Channel:
    channel = Channel(
        youtube_channel_id=channel_id,
        name=name,
        handle=handle,
        url=f"https://youtube.com/channel/{channel_id}",
        subscriber_count=1,
        total_views=1,
        video_count=1,
    )
    db.add(channel)
    db.commit()
    return channel


def test_search_costs_a_hundred_times_a_lookup():
    """The premise the rest of this file rests on."""
    assert QUOTA_UNITS["search"] == 100
    assert DEFAULT_QUOTA_UNITS == 1


def test_units_are_counted_per_call(monkeypatch):
    """A search must register as 100, not as one call like everything else."""
    from app.services import youtube as youtube_module

    class _OK:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {"items": []}

    monkeypatch.setattr(youtube_module.httpx, "get", lambda *a, **k: _OK())
    provider = RealYouTubeProvider("key")

    provider._get("channels", id="x")
    assert provider.units_used == 1

    provider._get("search", q="x")
    assert provider.units_used == 101

    provider._get("playlistItems", playlistId="x")
    assert provider.units_used == 102


def test_handle_guess_is_tried_before_paying_for_search(monkeypatch):
    """A /c/Slug URL resolves via forHandle (1 unit) when the slug is the
    handle, instead of going straight to a 100-unit search."""
    from app.services import youtube as youtube_module

    calls: list[dict] = []

    class _Resp:
        def __init__(self, payload: dict) -> None:
            self.status_code = 200
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    channel_item = {
        "id": "UC" + "z" * 22,
        "snippet": {"title": "Slugged", "customUrl": "@slug", "thumbnails": {}},
        "statistics": {"subscriberCount": "1", "viewCount": "1", "videoCount": "1"},
        "contentDetails": {"relatedPlaylists": {"uploads": "UU" + "z" * 22}},
    }

    def fake_get(url, params=None, timeout=None):
        calls.append(params or {})
        return _Resp({"items": [channel_item]})

    monkeypatch.setattr(youtube_module.httpx, "get", fake_get)
    provider = RealYouTubeProvider("key")

    provider.resolve_channel("https://youtube.com/c/Slug")

    assert any("forHandle" in c for c in calls), "should guess the handle first"
    assert not any("q" in c for c in calls), "should never reach the 100-unit search"
    assert provider.units_used == 1


def test_known_channel_id_skips_the_api(db):
    _store(db, channel_id="UC" + "a" * 22, handle="someone")
    provider = _FakeProvider()

    result = ingestion.resolve_and_store_channel(
        db, "https://youtube.com/channel/UC" + "a" * 22, provider
    )

    assert provider.calls == [], "a channel already stored must not be re-resolved"
    assert result.youtube_channel_id == "UC" + "a" * 22


def test_known_handle_skips_the_api(db):
    """The expensive case: without this, the 51st user adding the same
    competitor pays the same 100 units as the first."""
    _store(db, channel_id="UC" + "b" * 22, handle="mrbeast")
    provider = _FakeProvider()

    result = ingestion.resolve_and_store_channel(db, "https://youtube.com/@MrBeast", provider)

    assert provider.calls == []
    assert result.handle == "mrbeast"


def test_handle_match_is_case_insensitive(db):
    _store(db, channel_id="UC" + "c" * 22, handle="MrBeast")
    provider = _FakeProvider()

    ingestion.resolve_and_store_channel(db, "@mrbeast", provider)

    assert provider.calls == []


def test_custom_url_slug_matches_a_stored_handle(db):
    """/c/Slug parses as "search" — the 100-unit path — but the slug is usually
    the handle, so a stored channel should still short-circuit it."""
    _store(db, channel_id="UC" + "d" * 22, handle="veritasium")
    provider = _FakeProvider()

    ingestion.resolve_and_store_channel(db, "https://youtube.com/c/Veritasium", provider)

    assert provider.calls == []


def test_unknown_channel_still_hits_the_provider(db):
    provider = _FakeProvider()

    result = ingestion.resolve_and_store_channel(db, "@nobodyhasthisyet", provider)

    assert len(provider.calls) == 1, "a channel we don't hold must still be resolved"
    assert result.name == "Fresh Channel"


def test_channel_name_is_never_used_for_matching(db):
    """Two channels can share a display name. Silently tracking the wrong
    competitor is worse than spending a quota unit."""
    _store(db, channel_id="UC" + "e" * 22, handle=None, name="Tech Reviews")
    provider = _FakeProvider()

    ingestion.resolve_and_store_channel(db, "Tech Reviews", provider)

    assert len(provider.calls) == 1


def test_null_handle_does_not_swallow_lookups(db):
    """A stored channel with handle=None must not match arbitrary searches."""
    _store(db, channel_id="UC" + "f" * 22, handle=None)
    provider = _FakeProvider()

    ingestion.resolve_and_store_channel(db, "@somethingelse", provider)

    assert len(provider.calls) == 1


@pytest.mark.parametrize(
    "raw,kind",
    [
        ("https://youtube.com/channel/UC" + "g" * 22, "id"),
        ("https://youtube.com/@handle", "handle"),
        ("@handle", "handle"),
        ("https://youtube.com/c/CustomName", "search"),
        ("just a name", "search"),
    ],
)
def test_identifier_parsing_drives_the_cost(raw, kind):
    assert parse_identifier(raw)[0] == kind

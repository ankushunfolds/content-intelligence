"""Section 25 — the MVP acceptance test, executed literally.

    signup -> add own channel -> add 5 competitors -> collect -> analyse ->
    detect trends -> detect breakouts -> daily brief

If any step here needs manual intervention, the MVP is not finished.
"""
from __future__ import annotations

COMPETITORS = ["@signalstudio", "@buildlog", "@creatorlab", "@deepworkmedia", "@practicalai"]


def test_health_reports_the_active_providers(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["youtube_provider"] in {"live", "seed"}


def test_full_acceptance_workflow(client, auth):
    # --- Onboarding: exactly three inputs (Section 6) ---
    response = client.post(
        "/channels/onboarding",
        json={"own_channel": "@mychannel", "competitors": COMPETITORS, "niche": "AI / Technology"},
        headers=auth,
    )
    assert response.status_code == 201, response.text
    assert len(response.json()) == 6  # own + 5 competitors

    tracked = client.get("/channels/tracked", headers=auth).json()
    assert {row["type"] for row in tracked} == {"own", "competitor"}

    # --- The system collects, analyses, and reasons without being told how ---
    summary = client.post("/intelligence/refresh", headers=auth).json()
    assert summary["channels_ingested"] == 6
    assert summary["videos_classified"] >= 0
    assert summary["brief_date"] is not None

    # --- Videos arrived with real metrics ---
    channel_id = tracked[0]["id"]
    videos = client.get(f"/channels/{channel_id}/videos", headers=auth).json()
    assert videos, "ingestion produced no videos"
    assert all(v["views"] > 0 for v in videos)
    assert all(v["intelligence"]["performance_ratio"] is not None for v in videos)

    # --- Every video carries usable structured intelligence (Phase 4 criteria) ---
    assert all(v["intelligence"]["topic"] for v in videos)
    assert all(v["intelligence"]["format"] for v in videos)

    # --- Trends are ranked and inspectable ---
    trends = client.get("/trends", headers=auth).json()
    assert trends, "no trends detected from real data"
    assert trends == sorted(trends, key=lambda t: t["trend_score"], reverse=True)
    assert all(0 <= t["trend_score"] <= 100 for t in trends)
    assert all("signals" in t["components"] for t in trends), "trend score is not inspectable"

    # --- The brief answers the three questions ---
    brief = client.get("/briefs/today", headers=auth).json()["content"]
    assert brief["headline"]
    assert brief["opportunities"] or brief["competitor_highlights"]

    for opportunity in brief["opportunities"]:
        assert opportunity["why_it_matters"]        # "why does it matter?"
        assert opportunity["suggested_direction"]   # "what could I create?"
        assert opportunity["evidence"]["creator_count"] >= 1
        assert 0 <= opportunity["momentum"] <= 100

    # --- Section 13 caps ---
    assert len(brief["opportunities"]) <= 5
    assert len(brief["competitor_highlights"]) <= 3
    assert len(brief["rising_trends"]) <= 5


def test_opportunities_require_performance_not_just_volume(client, auth):
    """A topic being published more, while underperforming, is not an opportunity."""
    client.post(
        "/channels/onboarding",
        json={"own_channel": "@mychannel", "competitors": COMPETITORS},
        headers=auth,
    )
    client.post("/intelligence/refresh", headers=auth)

    brief = client.get("/briefs/today", headers=auth).json()["content"]
    for opportunity in brief["opportunities"]:
        ratio = float(opportunity["evidence"]["avg_performance"].rstrip("×"))
        assert ratio >= 1.0


def test_breakouts_are_relative_to_each_creator(client, auth):
    client.post(
        "/channels/onboarding",
        json={"own_channel": "@mychannel", "competitors": COMPETITORS},
        headers=auth,
    )
    client.post("/intelligence/refresh", headers=auth)

    for video in client.get("/videos/breakouts", headers=auth).json():
        intel = video["intelligence"]
        assert intel["is_breakout"]
        assert intel["performance_ratio"] >= 3.0
        assert video["views"] >= intel["baseline_views"]


def test_dashboard_loads_in_one_call(client, auth):
    client.post(
        "/channels/onboarding",
        json={"own_channel": "@mychannel", "competitors": COMPETITORS[:2]},
        headers=auth,
    )
    client.post("/intelligence/refresh", headers=auth)

    payload = client.get("/intelligence/today", headers=auth).json()
    for key in ("headline", "opportunities", "breakouts", "rising_trends", "competitor_activity", "stats"):
        assert key in payload


def test_brief_is_cached_not_regenerated_per_request(client, auth):
    """Cost control (Section 27): reading the brief twice must not cost twice."""
    client.post("/channels/onboarding", json={"own_channel": "@mychannel", "competitors": COMPETITORS[:2]}, headers=auth)
    client.post("/intelligence/refresh", headers=auth)

    first = client.get("/briefs/today", headers=auth).json()
    second = client.get("/briefs/today", headers=auth).json()
    assert first["id"] == second["id"]
    assert first["content"]["generated_at"] == second["content"]["generated_at"]


def test_classification_does_not_repeat_work(client, auth):
    client.post("/channels/onboarding", json={"own_channel": "@mychannel", "competitors": COMPETITORS[:2]}, headers=auth)
    client.post("/intelligence/refresh", headers=auth)

    again = client.post("/intelligence/refresh", headers=auth).json()
    assert again["videos_classified"] == 0, "already-classified videos were re-sent to the LLM"


def test_competitor_limit_is_enforced(client, auth):
    client.post("/channels/onboarding", json={"own_channel": "@mine", "competitors": []}, headers=auth)
    for i in range(10):
        assert client.post("/channels/track", json={"url": f"@competitor{i}"}, headers=auth).status_code == 201
    overflow = client.post("/channels/track", json={"url": "@competitor11"}, headers=auth)
    assert overflow.status_code == 400


def test_endpoints_reject_anonymous_requests(client):
    for path in ("/channels/tracked", "/trends", "/briefs/today", "/intelligence/today", "/videos/breakouts"):
        assert client.get(path).status_code == 401


def test_concurrent_track_of_the_same_new_channel_does_not_500(client, auth):
    """Regression test: two near-simultaneous requests for the same brand-new
    channel (a double-click, or two open tabs) both used to race past the
    'does this channel exist yet' check and one would crash with a raw
    IntegrityError instead of a clean 201."""
    import threading

    results: list[int] = []
    lock = threading.Lock()

    def track():
        r = client.post("/channels/track", json={"url": "@raceclickchannel"}, headers=auth)
        with lock:
            results.append(r.status_code)

    threads = [threading.Thread(target=track) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [201, 201]
    tracked = client.get("/channels/tracked", headers=auth).json()
    matches = [c for c in tracked if c["name"].lower().replace(" ", "") == "raceclickchannel"]
    assert len(matches) == 1, "the race must not create duplicate channel or tracking rows"


def test_removing_all_channels_clears_stale_signal(client, auth):
    """Regression test: untracking every channel used to leave the day's cached
    brief (and the underlying trend rows) showing yesterday's opportunities and
    momentum scores as if they still applied. Nothing should claim there's a
    signal once the data behind it is gone."""
    tracked = client.post(
        "/channels/onboarding",
        json={"own_channel": "@mychannel", "competitors": COMPETITORS},
        headers=auth,
    ).json()
    client.post("/intelligence/refresh", headers=auth)
    # Prime today's cache with whatever signal exists before removing channels.
    client.get("/intelligence/today", headers=auth)

    for channel in tracked:
        client.delete(f"/channels/{channel['id']}", headers=auth)

    body = client.get("/intelligence/today", headers=auth).json()
    assert body["opportunities"] == []
    assert body["rising_trends"] == []
    assert "not enough signal" in body["headline"].lower()


def test_admin_routes_require_admin_not_just_login(client, auth):
    """A regular signed-up user is not an admin. Regression test: /admin/* used to
    accept any authenticated user, leaking every user's channel names and pipeline
    logs to whoever else happened to have an account."""
    assert client.get("/admin/stats").status_code == 401       # no token at all
    assert client.get("/admin/stats", headers=auth).status_code == 403   # logged in, not admin
    assert client.get("/admin/events", headers=auth).status_code == 403


def test_admin_emails_grants_access_at_signup(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_emails", {"root@example.com"})
    token = client.post(
        "/auth/signup", json={"email": "root@example.com", "password": "secret123"}
    ).json()["access_token"]
    admin_auth = {"Authorization": f"Bearer {token}"}
    assert client.get("/admin/stats", headers=admin_auth).status_code == 200


def test_users_cannot_see_each_others_channels(client):
    a = client.post("/auth/signup", json={"email": "a@x.com", "password": "secret123"}).json()
    b = client.post("/auth/signup", json={"email": "b@x.com", "password": "secret123"}).json()
    head_a = {"Authorization": f"Bearer {a['access_token']}"}
    head_b = {"Authorization": f"Bearer {b['access_token']}"}

    created = client.post("/channels/track", json={"url": "@privatechannel"}, headers=head_a)
    channel_id = created.json()["id"]

    assert client.get(f"/channels/{channel_id}", headers=head_a).status_code == 200
    assert client.get(f"/channels/{channel_id}", headers=head_b).status_code == 404
    assert client.get(f"/channels/{channel_id}/videos", headers=head_b).status_code == 404

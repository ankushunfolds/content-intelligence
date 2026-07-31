# Content Intelligence — MVP v1.0

A YouTube content intelligence system that watches a creator's competitors, identifies unusually successful content and emerging trends, and turns those signals into a concise daily briefing telling the creator what deserves attention and why.

The product answers one question: **"What should I create next, and why?"**

---

## Run it

```bash
./dev.sh
```

That's it. It creates `.env`, installs both dependency sets, and starts the API on `:8000` and the frontend on `:3000`. **No API keys are needed** — the default config uses deterministic seed data and a keyword-based classifier, so the entire pipeline runs and can be demoed offline.

Want data in the account before you sign in?

```bash
cd backend && python scripts/seed_demo.py     # demo@contentintelligence.app / demo1234
```

### Running the pieces separately

```bash
# API
cd backend && pip install -r requirements.txt
uvicorn app.main:app                     # http://localhost:8000/docs

# Frontend
cd frontend && npm install && npm run dev # http://localhost:3000

# Background jobs
cd backend && python -m app.workers.scheduler --once        # one full cycle
python -m app.workers.scheduler --job ingest                # a single job
python -m app.workers.scheduler                             # loop every 6h

# Tests
cd backend && pytest                      # 31 tests
```

### Postgres and Redis

SQLite is the default so nothing has to be installed. For the real stack:

```bash
docker compose up -d
pip install -r backend/requirements-optional.txt   # psycopg3 + redis

# then in .env:
DATABASE_URL=postgresql+psycopg://ci:ci@localhost:5432/content_intelligence
```

### Going live

Two switches in `.env`, independent of each other:

```bash
YOUTUBE_PROVIDER=youtube      # real YouTube Data API v3
YOUTUBE_API_KEY=...

LLM_PROVIDER=openai           # or: gemini
OPENAI_API_KEY=...
```

If a provider is selected but its key is missing, the system logs a warning and falls back to the mock rather than crashing. `GET /health` always tells you which mode you're actually in.

---

## How it works

```
YOUTUBE → INGESTION → DATABASE
                          ↓
              ┌───────────┴───────────┐
       PERFORMANCE ENGINE      CLASSIFICATION
       (Python, deterministic)  (LLM, semantic)
              └───────────┬───────────┘
                          ↓
                    TREND ENGINE
                          ↓
                   BRIEF SELECTION      ← Python picks the signals
                          ↓
                        LLM             ← writes the explanation only
                          ↓
                    DAILY BRIEF
```

The load-bearing rule, from §14 of the spec: **Python decides what is true, the LLM decides how to say it.** Nothing in `performance.py` or `trends.py` calls a model, and the brief prompt receives finished numbers it is forbidden to alter. `tests/test_llm_grounding.py` enforces this by asserting that every number in generated prose traces back to the input.

### Performance is relative to the creator

Ranking by raw views would just rank by audience size. Instead:

```
performance_ratio = video_views / creator_median_views
```

Median, not mean, so one viral video doesn't raise a channel's own bar. Videos under 3 days old are excluded from the baseline (still climbing) but are still scored against it. A 50K-subscriber channel at 200K views therefore outranks a 5M-subscriber channel at 500K — which is the point.

A video at or above `BREAKOUT_THRESHOLD` (default 3.0×) is a breakout.

### The trend score is arithmetic you can audit

A trend isn't "people talked about AI". It's "AI-agent videos are appearing more often *and* beating their creators' baselines". Five weighted signals, each normalised against a saturation point:

| Signal | Weight | Saturates at |
|---|---|---|
| Average performance | 0.30 | 3× baseline |
| Volume growth vs prior window | 0.25 | +100% |
| Creator adoption | 0.20 | 8 creators |
| Breakout rate | 0.15 | 40% of videos |
| Publishing velocity | 0.10 | 2 videos/day |

1× performance contributes exactly zero — being merely average shouldn't earn score. Every component, its raw value, its normalised value and its point contribution are stored on the trend row and rendered in the UI under "How this score was built". If a recommendation looks wrong, you can see precisely which signal caused it.

One deliberate refinement beyond the spec: a topic that is rising in *volume* while *underperforming* appears under "rising trends" but is **not** promoted to an opportunity (`OPPORTUNITY_MIN_PERFORMANCE`). Publishing more of something that isn't working is not an opportunity.

### Cost control

- Each video is classified exactly **once**, in batches of 20, from its title alone.
- Briefs are generated once per day and cached; re-reading costs nothing.
- All scoring is Python. The LLM is called twice per day per user at most.
- Every LLM failure degrades to the deterministic path and is logged, never raised to the user.

---

## Layout

```
backend/
  app/
    api/         auth · channels · videos · trends · briefs · intelligence · admin
    models/      users · channels · tracked_channels · videos · video_intelligence · trends · daily_briefs · event_log
    services/    youtube · ingestion · performance · classification · llm · trends · briefing · pipeline
    workers/     jobs.py (the four background jobs) · scheduler.py (entrypoint)
    utils/       security · logging · time · format
  tests/         31 tests, incl. the §25 acceptance workflow end-to-end
  scripts/       seed_demo.py

frontend/
  app/           / · /onboarding · /dashboard · /competitors · /competitors/[id] · /trends · /briefs
  components/    OpportunityCard · CompetitorCard · TrendCard · BreakoutVideo · Metric · Shell
  lib/           api client · types · formatters
```

## API

```
POST   /auth/signup              POST   /auth/login           GET  /auth/me

POST   /channels/onboarding      # own channel + competitors + niche, one call
POST   /channels/track           GET    /channels/tracked
GET    /channels/{id}            DELETE /channels/{id}
GET    /channels/{id}/videos     ?sort=recent|performance|views

GET    /videos/breakouts

GET    /trends                   GET    /trends/{id}
GET    /trends/{id}/videos       # the evidence behind a trend
POST   /trends/recompute

GET    /intelligence/today       # everything the dashboard needs, one call
POST   /intelligence/refresh     # run the full pipeline now

GET    /briefs                   GET    /briefs/today
GET    /briefs/{date}            POST   /briefs/regenerate

GET    /admin/events             GET    /admin/stats          GET /health
```

---

## Notes on choices

**SQLite default.** Postgres is the production target and `docker-compose.yml` is there for it, but requiring a database daemon to run the app for the first time is friction the MVP doesn't need. One env var switches it.

**Loop, not Celery.** `workers/scheduler.py` is a plain interval loop with an optional Redis lock. A handful of creators and four cycles a day does not justify a broker topology, and this is trivial to swap out when it does.

**No Pandas/DuckDB yet.** The spec lists them, but the aggregations here run over a few thousand rows and are clearer — and more testable — as plain Python. Worth adding when the dataset or the query complexity actually calls for it.

**Auth is stdlib.** PBKDF2 plus signed, expiring tokens. No bcrypt build step, no extra dependency, and swappable for real JWT/OAuth without touching anything outside `utils/security.py`.

## Deliberately not built (§3)

No script writing, image or thumbnail generation, scheduling, content calendar, CRM, team features, mobile app, multi-platform analytics, or billing. If a feature doesn't help answer "what should I create next, and why?", it isn't in v1.

## Acceptance

`tests/test_acceptance.py` runs the §25 workflow literally — signup → add own channel → add 5 competitors → collect → analyse → detect trends → detect breakouts → daily brief — and asserts no step needs manual intervention. It also checks the §13 section caps, that opportunities require performance and not just volume, that breakouts are creator-relative, that briefs are cached rather than regenerated per request, that classification never repeats work, and that one user cannot see another's channels.

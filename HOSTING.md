# Pushing to GitHub and hosting on Railway

## Why you run these commands, not Claude

Pushing to GitHub and deploying to Railway both need your own login — a GitHub
personal account and a Railway account. Claude doesn't handle passwords, API
keys, or tokens on your behalf, so every step below runs in your own Terminal,
using your own credentials. Everything else (the repo structure, Procfile,
Postgres URL handling, CORS config) is already done.

---

## 1. Push to GitHub

A stray, empty `.git/` folder may already exist in this directory from setup —
remove it first so you start clean:

```bash
cd "/Users/ankush/AnkushUnfolds/Content Intelligence/app"
rm -rf .git
```

**If you have the GitHub CLI** (`gh`) — this creates the repo under
`ankushunfolds` and pushes in one step:

```bash
git init
git add -A
git commit -m "Content Intelligence MVP v1.0"

gh auth login          # skip if already logged in as ankushunfolds
gh repo create ankushunfolds/content-intelligence --public --source=. --remote=origin --push
```

**Without `gh`** — create the repo manually first:

1. Go to https://github.com/new, owner **ankushunfolds**, name
   `content-intelligence`, visibility **public**, do NOT initialize with a
   README (this folder already has one).
2. Then:

```bash
git init
git add -A
git commit -m "Content Intelligence MVP v1.0"
git branch -M main
git remote add origin https://github.com/ankushunfolds/content-intelligence.git
git push -u origin main
```

`.gitignore` already excludes `.env`, `*.db`, `node_modules/`, `.venv/`, and
`.next/` — your API keys and local database will not be committed. Worth a
quick look before the first push:

```bash
git status
```

Nothing named `.env` (without `.example`) or `*.db` should appear.

---

## 2. Host on Railway

Railway runs the FastAPI backend, the background worker, and Postgres in one
project. The Next.js frontend goes there too, as a fourth service.

### 2.1 Create the project

1. https://railway.app → New Project → **Deploy from GitHub repo** →
   `ankushunfolds/content-intelligence`.
2. Add Postgres: **New** → **Database** → **PostgreSQL**. Railway injects a
   `DATABASE_URL` into every other service in the project automatically once
   you reference it (step 2.3).

### 2.2 Backend service (`web`)

Add a service from the same repo, then in its **Settings**:

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Start Command | leave blank — the `Procfile`'s `web:` line is picked up automatically |

**Variables** tab — add:

```
DATABASE_URL       = ${{Postgres.DATABASE_URL}}
SECRET_KEY         = <run: python3 -c "import secrets; print(secrets.token_hex(32))">
CORS_ORIGINS       = https://<your-frontend-service>.up.railway.app
YOUTUBE_PROVIDER   = mock        # switch to "youtube" once you have a key
YOUTUBE_API_KEY    =
LLM_PROVIDER       = mock        # switch to "openai" or "gemini" once you have a key
OPENAI_API_KEY     =
GEMINI_API_KEY     =
```

`${{Postgres.DATABASE_URL}}` is Railway's variable-reference syntax — it
resolves to the Postgres service's real connection string, which arrives as a
bare `postgres://` URL. `app/config.py` already rewrites that to
`postgresql+psycopg://` on startup, so no manual editing needed.

Once deployed, copy this service's public URL (Settings → Networking →
Generate Domain if it isn't there yet) — you'll need it for the frontend.

### 2.3 Worker service

Add another service from the same repo:

| Setting | Value |
|---|---|
| Root Directory | `backend` |
| Start Command | `python -m app.workers.scheduler` (overrides the Procfile's `web:` line) |
| Variables | same as the backend service — copy them over, or use Railway's "Shared Variables" |

This is the process that runs ingestion → analysis → trends → briefs on a
schedule (every 6 hours, `INTERVAL_SECONDS` in `app/workers/scheduler.py`).
Without it, data only refreshes when a user hits **Refresh** or **Onboarding**
in the app.

### 2.4 Frontend service

Add a third service from the same repo:

| Setting | Value |
|---|---|
| Root Directory | `frontend` |
| Start Command | leave blank — Railway's Nixpacks detects Next.js (`npm run build` / `npm run start`) |

**Variables**:

```
NEXT_PUBLIC_API_URL = https://<your-backend-service>.up.railway.app
```

Deploy, then copy *this* service's public URL and go back to the backend
service's `CORS_ORIGINS` variable (step 2.2) to set it — the two services'
URLs reference each other, so the first deploy of each needs a follow-up
variable update once both domains exist.

### 2.5 Verify

```bash
curl https://<backend-url>/health
```

Should return `{"status":"ok", ...}`. Then open the frontend URL in a browser
and sign up.

---

## 3. Switching from seed data to real data

Once hosting works end-to-end on seed/mock data, flip these on the **backend**
service (Railway → Variables) and redeploy:

```
YOUTUBE_PROVIDER = youtube
YOUTUBE_API_KEY  = <your key>

LLM_PROVIDER     = gemini        # or openai
GEMINI_API_KEY   = <your key>
```

See the main README's "How it works" section for what each key costs to run
and where to get them.

---

## 4. Redeploys

Railway redeploys automatically on every push to `main`:

```bash
git add -A
git commit -m "..."
git push
```

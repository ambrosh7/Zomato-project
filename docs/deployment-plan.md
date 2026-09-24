# Deployment plan

Deploy the Bangalore recommender as two services:

| Piece | Host | What ships |
| --- | --- | --- |
| API | Railway | FastAPI in `src/`, catalog at `data/catalog.sqlite`, Groq ranker |
| Frontend | Vercel | Latest static UI in `web/` (`index.html`, `app.js`, `styles.css`, `hero.svg`) |

`stitch_bangalore_food_tech_recommender_ui/` is the design source. Do not deploy it. The page users should see is `web/`.

Today one process serves both. `web/app.js` calls `/health`, `/api/meta`, and `/api/recommendations` on the same origin, and Phase 5 left CORS off for that reason. Keep that contract: the browser still talks to the Vercel origin, and Vercel proxies those three paths to Railway.

```text
Browser
  → Vercel (web/)
      / , /styles.css, /app.js     served as static files
      /health, /api/*              rewritten to Railway
  → Railway (FastAPI)
      loads data/catalog.sqlite
      POST /api/recommendations → filter → Groq (or fallback)
```

Deploy the API first. The Vercel rewrite needs the public Railway URL.

## What must change before the first deploy

The app runs locally as `python src/api.py`, which binds `127.0.0.1:8000`. Railway will not accept traffic on that address, and it injects its own `PORT`. Do not use `python src/api.py` as the start command.

`src/` is not a package. Modules import each other by bare name (`import catalog`). The start command has to put `src` on the import path. Catalog paths are resolved from the repo root (`parents[1]` of `src/catalog.py`), so the process working directory stays the repo root and `CATALOG_PATH=data/catalog.sqlite` keeps working.

### 1. Production start command

Add `railway.toml` at the repo root:

```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "uvicorn api:create_app --factory --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "ON_FAILURE"
```

`create_app` is already a zero-argument factory, so uvicorn can call it. `--app-dir src` is what makes `import catalog` succeed.

### 2. Runtime dependencies only

`requirements.txt` currently includes `datasets`, which is only used by `scripts/inspect_dataset.py` and the Hugging Face download path. The request path reads SQLite and calls Groq with the standard library. Installing `datasets` on Railway pulls a large stack and slows every build.

Move the install split to:

`requirements.txt` (what Railway installs):

```text
python-dotenv>=1,<2
fastapi>=0.111,<1
uvicorn>=0.30,<1
```

`requirements-dev.txt` (local ingest and tests only):

```text
-r requirements.txt
datasets>=2.19,<4
```

Python is 3.11 or newer. `.python-version` is `3.11`. Nixpacks will follow that file. Do not point Railway at `.venv`.

### 3. Ship the SQLite catalog, not the raw CSV

| File | Size | Deploy? |
| --- | --- | --- |
| `data/catalog.sqlite` | 5.8 MB | Yes. This is what `catalog.load()` reads. |
| `data/catalog.csv` | 1.5 MB | No. Not read at runtime. |
| `data/zomato.csv` | 547 MB | No. Already gitignored. Contains columns the app refuses to send to the model. |
| `data/groq-usage.json` | small | No. Already gitignored. Recreated on the server. |

Confirm `.gitignore` still excludes `.env`, `.venv/`, `data/zomato.csv`, and `data/groq-usage.json`. `data/catalog.sqlite` must be committed. There is no volume and no Hugging Face download on boot. If the sqlite file is missing, `/health` stays `failed` and recommendations return 503.

### 4. Vercel rewrite file

Add `web/vercel.json` after the Railway URL exists. Replace the host; do not commit a placeholder.

```json
{
  "rewrites": [
    { "source": "/health", "destination": "https://YOUR-SERVICE.up.railway.app/health" },
    { "source": "/api/:path*", "destination": "https://YOUR-SERVICE.up.railway.app/api/:path*" }
  ]
}
```

Leave `web/app.js` on relative URLs. A rewrite keeps the page and the API same-origin, so CORS stays off and preview deploys keep working.

Groq calls time out at 20 seconds (`TIMEOUT_SECONDS` in `src/ranker.py`). If a Vercel proxy cuts the POST off before that, switch to a direct browser call: set `CORSMiddleware` on the API to the exact Vercel origin, and prefix the three `fetch` calls with that origin. Do not use `allow_origins=["*"]` while `GROQ_API_KEY` is on the API.

## GitHub

This folder is not a git repository. Railway and Vercel both deploy from GitHub.

1. Create a new GitHub repo for this project. Do not push it into `ambrosh7/TestProject`.
2. Initialize git here and push `main`.
3. Confirm the remote does not contain `.env`, `tests/.env`, `.venv/`, or `data/zomato.csv`.
4. Confirm `data/catalog.sqlite` is in the commit.

Both platforms should track `main`. Root directory on Railway is the repo root. Root directory on Vercel is `web`.

## Railway — API

1. New project → Deploy from GitHub → this repo.
2. Service root: repository root. Builder: Nixpacks (from `railway.toml`).
3. Instances: **1**. The Groq limiter in `src/ranker.py` counts usage inside one process and writes `data/groq-usage.json`. A second instance would keep its own counter and could exceed the model’s 1,000 requests/day and 200,000 tokens/day. The file lives on ephemeral disk, so a restart or redeploy resets the local counter. Groq still enforces the real quota; the local limiter is best-effort until the next boot.
4. Variables (service scope, not committed):

| Variable | Value |
| --- | --- |
| `CATALOG_PATH` | `data/catalog.sqlite` |
| `GROQ_API_KEY` | from the local `.env` only. Never put this on Vercel. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` |
| `GROQ_API_BASE_URL` | `https://api.groq.com/openai/v1` |

`PORT` is set by Railway. Do not override it.

5. Generate a public domain. Copy the `https://….up.railway.app` host into `web/vercel.json`.
6. Health check path: `/health`. That route returns HTTP 200 with `{"status":"loading"|"ready"|"failed"}`. A green check only means the process is listening. Wait until the body says `ready` before judging the catalog. SQLite load is in a background thread at startup and should finish well inside the UI’s 30 second poll.

Smoke test from a terminal, before touching Vercel:

```bash
curl -sS https://YOUR-SERVICE.up.railway.app/health
curl -sS https://YOUR-SERVICE.up.railway.app/api/meta
curl -sS -X POST https://YOUR-SERVICE.up.railway.app/api/recommendations \
  -H 'content-type: application/json' \
  -d '{"location":"Indiranagar","budget":"medium","cuisine":"Any","min_rating":3.5}'
```

Expect `/health` to reach `ready`, `/api/meta` to list Bangalore neighborhoods, and the POST to return `status: ok` with at most 5 results. `source` should be `llm` when Groq accepts the call, or `fallback` when the key is missing, the quota is spent, or the model output is rejected. Facts on the cards still come from the catalog in both cases.

`/docs` is disabled on purpose. Do not turn OpenAPI back on for production.

## Vercel — frontend

1. New project → import the same GitHub repo.
2. Framework preset: Other.
3. Root directory: `web`.
4. In Root Directory settings, turn **off** “Include files outside the root directory in the Build Step”. If that stays on, Vercel still sees root `requirements.txt` and tries to build FastAPI.
5. Build command: empty. Output directory: empty (the root directory is already the static site). Install command: empty. There is no `package.json`.
6. No environment variables. The Groq key must not be added here. Fonts load from Google Fonts in the browser.
7. Deploy from the latest `main` commit. Do not redeploy an older failed Production deployment once a newer one exists.
8. Commit `web/vercel.json` with the real Railway host and redeploy.

Production URL is `https://<project>.vercel.app`. That is the URL to share. The Railway URL still serves `web/` as static files because `create_app` mounts `web/` at `/`. Treat that as a same-origin fallback, not the public UI.

## End-to-end checks

Run these on the Vercel URL, in the browser.

- [ ] The page is the Nocturne UI (Playfair / Plus Jakarta, “Find a table that fits”), not the Stitch HTML mock.
- [ ] The meta pill moves from “Connecting catalog” to “API meta connected”. Neighborhood and cuisine lists are filled from `/api/meta`, not hard-coded.
- [ ] Budget labels show rupee bands from the API.
- [ ] Indiranagar (or another known neighborhood), Medium, Any, minimum rating 3.5 returns 1 to 5 cards with name, cuisines, rating, votes, and `₹… for two`.
- [ ] A location outside the catalog (Delhi) does not return a guessed list.
- [ ] An impossible filter shows the three suggestions: lower the minimum rating, choose Any cuisine, widen the budget.
- [ ] With a bad `GROQ_API_BASE_URL` on Railway only, cards still render and the page does not invent explanations (`source: fallback`).
- [ ] View source or the network panel: recommendation requests go to the Vercel host (`/api/recommendations`), and `GROQ_API_KEY` never appears in the browser.

## After it is up

- Redeploy Railway on every API or catalog change. Redeploy Vercel on every `web/` change. A catalog rebuild means committing a new `data/catalog.sqlite` and redeploying Railway only.
- Rotate `GROQ_API_KEY` in the Railway variables UI. Redeploy is not required for variable edits if Railway restarts the service on change; confirm `/api/recommendations` still returns `source: llm`.
- Keep a single Railway instance. If the local limiter resets on every deploy, that is expected; do not raise `GROQ_MODEL` limits in code to compensate.
- Custom domains can be attached later on each platform. If the public site host changes, update the rewrite only if you moved off the Vercel rewrite and onto CORS.
- Logs: Railway should show catalog load, then either a Groq completion or a fallback. Do not log the full prompt. It must never contain phone numbers or review text. Those columns are not in the sqlite catalog.

## Out of scope

- A database, queue, login, or file volume
- Serving `data/zomato.csv` or downloading the Hugging Face dataset on boot
- Deploying `stitch_bangalore_food_tech_recommender_ui/`
- More than one API instance
- Putting the Groq key in the frontend or in git

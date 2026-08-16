# LinkPlease — Intern Assignment

A small, reliable DM-automation system built on top of the PseudoGram
mock Instagram API. Someone comments a keyword, and they get DMed
exactly once — even though PseudoGram redelivers events, reorders them,
rate-limits, and lies about delivery.

> The README's three routes (`POST /webhook`, `POST /rules`, `GET /stats`)
> are the graded contract and are implemented exactly as specified, at
> the exact paths, with no `/api` prefix. Everything else — Mongo,
> React, Render, Vercel — is an implementation choice the assignment
> left open.

## 1. Architecture

```
User → Vercel (React/Vite) → Render (FastAPI) → MongoDB Atlas
                                     ↓        ↑
                              PseudoGram API (webhook + DM send/status)
```

- **`POST /webhook`** validates the event, deduplicates it, matches
  rules, and writes a `dm_jobs` document — then returns. It never calls
  PseudoGram's DM API itself, which is how it stays under 5 seconds
  under load.
- **A background worker** (an `asyncio` task started in FastAPI's
  lifespan, not a separate process) claims queued jobs, sends DMs
  through a rate-limited client, retries on `429`/`500`, and reconciles
  `in_flight` jobs by polling `GET /v1/dm/{dm_id}` until they reach a
  terminal state.
- **MongoDB** is the single source of truth for everything — rules,
  seen event IDs, job status, retry counts, duplicate log. Nothing
  important lives only in process memory (see FAILURES.md #2–3 for the
  two things that *do*, and why).

## 2. MongoDB schema

| Collection | Purpose | Key index |
|---|---|---|
| `rules` | `{rule_id, keyword, dm_message, created_at}` | unique `rule_id` |
| `events` | `{event_id, event_type, processed_at}` — dedupes redelivered webhook events | unique `event_id` |
| `comments` | `{comment_id, user_id, text, deleted}` — lets a late `comment.deleted` suppress a not-yet-sent job, and lets an out-of-order `comment.deleted` suppress a not-yet-seen `comment.created` | unique `comment_id` |
| `dm_jobs` | `{rule_id, user_id, comment_id, dm_message, status, attempts, next_retry_at, dm_id, error, ...}` — one row per DM attempt lifecycle | unique compound `(rule_id, user_id)` |
| `duplicates_log` | one row per blocked duplicate, for `/stats` | — |

The two unique indexes (`events.event_id` and `dm_jobs.(rule_id,user_id)`)
are the actual duplicate-prevention mechanism — see "Duplicate
prevention" below.

## 3. Backend setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in MONGODB_URI and PSEUDOGRAM_API_KEY
uvicorn app.main:app --reload
```

Runs at `http://localhost:8000`. `/`, `/rules`, `/webhook`, `/stats` are
all live immediately; the worker task starts automatically.

## 4. Frontend setup

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000
npm run dev
```

## 5. Environment variables

Backend (`backend/.env`, see `.env.example`):

| Var | Meaning |
|---|---|
| `MONGODB_URI` | Atlas connection string |
| `MONGODB_DB_NAME` | database name |
| `PSEUDOGRAM_BASE_URL` | `https://pseudogram-api.onrender.com` |
| `PSEUDOGRAM_API_KEY` | your key from `/v1/keygen` — **never commit this** |
| `ALLOWED_ORIGINS` | comma-separated list, e.g. local Vite origin + Vercel URL |
| `DM_MAX_ATTEMPTS` | bounded retry ceiling before a job is marked `failed` |
| `DM_WORKER_POLL_SECONDS` | idle poll interval for the background worker |
| `PSEUDOGRAM_RATE_LIMIT_PER_MINUTE` | 10, per the README |

Frontend (`frontend/.env`): `VITE_API_BASE_URL` — the deployed Render URL.
The PseudoGram key is **never** referenced anywhere in `frontend/`.

## 6. Testing

```bash
cd backend
pip install -r requirements.txt
python -m pytest -q
```

21 tests, all passing against a mocked Mongo (`mongomock-motor`) and a
mocked PseudoGram (`respx`) — no live network calls, no real Atlas
cluster needed to run the suite. Covers: rule creation, case-insensitive
substring matching, multi-rule matching, duplicate `event_id`, duplicate
`(rule_id, user_id)` including a genuine concurrent race via
`asyncio.gather`, out-of-order `comment.deleted`, signature validation
(valid/invalid/missing), `/stats` accuracy, and worker behavior on
`202`/`429`/`400`/`500`/reconciliation/comment-deleted-before-send.

## 7. Getting your PseudoGram API key (you run these, not me)

```bash
curl -X POST https://pseudogram-api.onrender.com/v1/apply \
  -H "Content-Type: application/json" \
  -d '{"name":"YOUR NAME","email":"you@example.com","phone":"+91...","linkedin_url":"https://linkedin.com/in/you"}'

curl -X POST https://pseudogram-api.onrender.com/v1/keygen \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com"}'
```

Put the returned `api_key` into `backend/.env` as `PSEUDOGRAM_API_KEY`
(and into Render's environment variables for the deployed version).

## 8. Deploying the backend to Render

1. Push this repo to GitHub.
2. New Web Service on Render → connect the repo, root directory `backend/`.
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Set the env vars from section 5 (real `MONGODB_URI`, real `PSEUDOGRAM_API_KEY`, `ALLOWED_ORIGINS` including your eventual Vercel URL).
6. Deploy, then verify the three exact routes yourself:
   ```bash
   curl https://YOUR-RENDER-URL/stats
   curl -X POST https://YOUR-RENDER-URL/rules -H "Content-Type: application/json" \
     -d '{"keyword":"PRICE","dm_message":"test"}'
   ```
   I have not deployed this myself — I don't have Render/Atlas/PseudoGram
   credentials of yours to do so. Run these checks before you submit.

## 9. Deploying the frontend to Vercel

1. New Project on Vercel → root directory `frontend/`.
2. Build command: `npm run build`. Output directory: `dist`.
3. Environment variable: `VITE_API_BASE_URL=https://YOUR-RENDER-URL`.
4. Deploy, then add the resulting Vercel URL to the backend's
   `ALLOWED_ORIGINS` on Render and redeploy the backend.

## 10. Testing against the real PseudoGram simulator

Once deployed:

```bash
# 1. Create at least one rule against your deployed backend
curl -X POST https://YOUR-RENDER-URL/rules -H "Content-Type: application/json" \
  -d '{"keyword":"PRICE","dm_message":"Here is our price list"}'

# 2. Fire the load simulator at your webhook
curl -X POST https://pseudogram-api.onrender.com/v1/simulate/start \
  -H "X-API-Key: $PSEUDOGRAM_API_KEY" -H "Content-Type: application/json" \
  -d '{"webhook_url":"https://YOUR-RENDER-URL/webhook","count":500,"duration_seconds":10}'
# -> returns {"run_id": "..."}

# 3. Give the worker a little time to drain the queue, then compare
curl -H "X-API-Key: $PSEUDOGRAM_API_KEY" \
  https://pseudogram-api.onrender.com/v1/simulate/RUN_ID/truth > truth.json

curl https://YOUR-RENDER-URL/stats > mine.json
diff <(python -m json.tool truth.json) <(python -m json.tool mine.json)
```

Do this before submitting — I could not run it myself without your
real API key and a live deployment.

## 11. Duplicate prevention (the load-bearing part)

Two different duplicate problems, two different unique indexes:

- **Redelivered events** (`events.event_id`, unique): the same
  `event_id` insert twice → the second raises `DuplicateKeyError` →
  webhook returns `200` and does nothing else.
- **Same user, same rule, twice** (`dm_jobs.(rule_id, user_id)`,
  unique): even from *different* events/comments, a second job insert
  for a user+rule pair already seen raises `DuplicateKeyError`. This is
  what actually makes concurrent duplicate comments race-safe — the
  race is resolved by MongoDB's atomic index enforcement, not by a
  Python-side "check then insert," which would have a TOCTOU race.
  This is tested directly with `asyncio.gather` firing 10 identical
  user+rule events concurrently (`test_concurrent_duplicate_comments_still_dedupe`).

## 12. Retry strategy

- `202` → job moves to `in_flight`, reconciled later via `GET /v1/dm/{dm_id}`.
- `429` → requeued at `now + Retry-After`, uncapped by the attempt limit's backoff formula (we trust their number).
- `500` / network error → exponential backoff with jitter (`min(60, 2^attempts)` + up to 25% jitter), capped at `DM_MAX_ATTEMPTS`, then `failed`.
- `400` → immediately `failed`, no retry (the README is explicit this won't help).
- `send_dm` always includes a stable `Idempotency-Key` derived from the job's own Mongo `_id`, so retrying a send after a crash or timeout reuses the same key — PseudoGram returns the original `dm_id` instead of creating a second DM.

## 13. Rate limiting

A shared, process-wide rolling-window limiter (`RollingWindowRateLimiter`)
gates every call to `send_dm` *before* it's made, not after a `429`
comes back. Under a 500-events/10s burst, jobs queue up in Mongo far
faster than they can be sent — that's fine, `/webhook` already returned
before any of that happens.

## 14. Known limitations

See `FAILURES.md` — it's the canonical, honest list. The short version:
in-memory rate limiter and worker loop assume a single backend
instance; there's no sweep for jobs orphaned by a crash mid-send; the
`comment.deleted` policy is a judgment call, not a spec.

## 15. Deployed links

_Not filled in — I did not deploy this. Fill in after you deploy:_
- Backend: `https://___.onrender.com`
- Frontend: `https://___.vercel.app`

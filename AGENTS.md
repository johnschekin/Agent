# AGENTS.md

## Purpose
Operational context for local development in this repo, with an emphasis on reliable dashboard startup/restart procedures.

## Server Startup Runbook (Use These Exact Commands)

### 1) Backend (FastAPI on 8000)
Run from `dashboard/`:

```bash
cd /Users/johnchtchekine/Projects/Agent/dashboard
python3 -m uvicorn api.server:app --host 127.0.0.1 --port 8000
```

Background variant:

```bash
cd /Users/johnchtchekine/Projects/Agent/dashboard
nohup python3 -m uvicorn api.server:app --host 127.0.0.1 --port 8000 > /tmp/ontology-links-backend.log 2>&1 &
```

Verify:

```bash
curl -s http://127.0.0.1:8000/api/health
```

### 2) Frontend (Next.js on 3000)
Run from `dashboard/`:

```bash
cd /Users/johnchtchekine/Projects/Agent/dashboard
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000 npm run dev -- --hostname 127.0.0.1 --port 3000
```

Important:
- Use `--hostname` (not `--host`).
- Set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` to avoid accidental same-origin `/api` calls to port `3000`.

Verify:

```bash
curl -s -o /dev/null -w "%{http_code}\n" 'http://127.0.0.1:3000/links?tab=review'
```

## Clean Restart Runbook

```bash
pkill -f "uvicorn api.server:app" || true
pkill -f "next dev --hostname 127.0.0.1 --port 3000" || true
```

Then start backend first, frontend second, using commands above.

## Common Failure Modes + Fixes

1. Frontend fails with `unknown option --host`
- Cause: wrong Next CLI flag.
- Fix: use `--hostname 127.0.0.1`.

2. Browser shows CORS/access-control errors to `localhost:3000/api/...`
- Cause: frontend calling same-origin API on 3000 instead of backend on 8000.
- Fix: start frontend with `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000`.

3. Backend appears "up" but API requests fail
- Check process and bind:
```bash
lsof -nP -iTCP:8000 -sTCP:LISTEN
```
- If needed, restart backend using the runbook.

4. Frontend appears "up" but page never loads data
- Check frontend log for compile/runtime errors.
- Confirm backend health on `:8000` and frontend URL on `:3000`.

## Notes

- Start backend and frontend as separate commands/sessions.
- Prefer `127.0.0.1` consistently for both services.

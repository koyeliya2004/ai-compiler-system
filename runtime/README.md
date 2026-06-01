# Runtime — Execution Artifacts

This folder is written by **Stage 6** of the pipeline at generation time.

## What gets generated

| File | Description |
|------|-------------|
| `schema.sql` | PostgreSQL DDL — run once to create all tables, indexes, FK constraints |
| `router.py` | FastAPI `APIRouter` — mount in your `main.py` with `app.include_router(router)` |
| `pages/<PageName>.tsx` | React page stubs — drop into your `src/pages/` directory |
| `docker-compose.yml` | Ready-to-run compose file — `docker compose up` to start API + DB |

## Quick start

```bash
# 1. Start the database
docker compose up db -d

# 2. Apply DDL
psql postgresql://postgres:postgres@localhost:5432/appdb -f schema.sql

# 3. Start API
uvicorn api.main:app --reload
```

## Execution score

Stage 6 computes an **execution score (0-100)**:

| Score | Status |
|-------|--------|
| 90-100 | Fully executable — zero manual fixes needed |
| 70-89 | Executable with minor TODOs (stub implementations) |
| 60-69 | Runnable but incomplete — some routes need logic |
| < 60 | Not executable — Stage 5 repair needed |

The score factors in DB completeness, API coverage, UI page coverage, auth configuration, and artifact quality.

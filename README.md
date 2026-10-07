# HELLOMYME Career

학교·학과·경력을 입력하면 "나와 비슷한 사람들이 실제로 선택한 다음 경로"를 집단 통계로 보여주고,
그 경로를 먼저 간 선배와 연결하는 Career Decision Network.

```
apps/api   FastAPI + PostgreSQL 16 (Alembic raw-SQL migrations, pytest)
apps/web   Next.js (App Router) — MVP flow scaffold
docs/      architecture review, pre-seed validation, migration list
scripts/   read-only data profiling
```

## Quick start

```bash
make db                     # PostgreSQL 16 via docker compose (dev + test databases)
cd apps/api && cp .env.example .env && uv sync && cd ../..
make migrate
make import-preseed CSV_DIR=/path/to/HELLOMYME_PreSeed_CSV_v1.2 VERSION=v1.2 AS_OF=2026-10-07
make api                    # http://localhost:8000/docs
cd apps/web && cp .env.example .env.local && npm install && cd ../..
make web                    # http://localhost:3000
make test
```

The pre-seed package is not committed. It is generated data for development, UX and engine
testing only: the app labels results built on it as `SIMULATION`, and refuses to start in
`production` if `PRE_SEED` is configured as a Career Map data layer.

## Core rules enforced in code

| Rule | Where |
|---|---|
| raw never overwritten | `source_record`, `verification_log`, `qa_review`, `audit_log` are append-only (DB trigger) |
| one WORK_EVENT ← N sources, field-level evidence | `work_event_source.supported_fields` |
| immutable MY ledger, corrections by reversal | `credit_ledger` trigger + `domain/ledger.py` |
| idempotent imports / rewards / unlocks / orders / merges | manifest hash, `entity_key_map`, `idempotency_key` uniques |
| configurable thresholds, rewards, costs | `cohort_policy`, `scoring_policy`, `reward_policy`, `unlock_policy`, `pricing_policy` |
| small-cohort suppression | `domain/cohort.py` (cohort) + `domain/career_map.py` (cell level) |
| PRE_SEED never identity-matched, never a mentor | DB trigger + mentor query filter |

## API (MVP)

`POST /career/draft` · `POST /career/draft/query` · `POST /auth/login` · `POST /auth/merge-draft` ·
`GET /career/map` · `POST /career/map/query` · `POST /career/unlock` · `POST /career/events` ·
`POST /career/events/{id}/reconfirm` · `GET /credits` · `GET /credits/ledger` ·
`POST /mentors/profile` · `POST /mentors/offers` · `GET /mentors/matches` · `GET /mentors/{id}` ·
`POST /orders` · `POST /analytics/events` · `GET /taxonomy/{kind}`

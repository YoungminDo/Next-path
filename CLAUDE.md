# HELLOMYME Career (Next-path)

Career Decision Network: input school/major/career → "what did similar people actually do next"
→ unlock deeper insight with 튜브 (internal credit) → connect with seniors who walked the path.
Will later merge into Hello My Me. Read `docs/` before large changes:
`00_ARCHITECTURE_REVIEW.md` (original review), `01_PRESEED_V12_VALIDATION_AND_MIGRATIONS.md`
(validation, migration list, decision log), `02_HMM_ID_INTEGRATION.md` (login),
`03_DEPLOYMENT.md` (deploy status and steps), `07_SERVICE_DESIGN.html` (service design),
`08_DATA_MOAT.md` (which source data is the moat; migration 0019), `09_INGESTION_PIPELINE.md`
(capture → AI JSON → checks → field review → SEED; migration 0022), `10_DEMAND_TEST.md` (funnel
events from `web/lib/track.ts`, migration 0024, `scripts/funnel.sql`; one 방문 definition `admin_stats.visits` (§방문); inputs as data + desired roles 0026,
interview phone opt-in 0027; resume/capture import 0030: `domain/career_import.py`, web `components/ImportFlow.tsx`,
`/upload`), `11_META_ADS.md` (per-audience Meta campaigns, utm_campaign `np_<date>_<audience>`, pixel `web/lib/pixel.ts`,
dataset NEXTPATH웹 in `lib/pixel-id.ts`, `NEXT_PUBLIC_META_PIXEL_ID=off` turns it off: PageView/Lead/CompleteRegistration, no properties), `12_SEARCH_INGEST.md` (design: SerpAPI + Brave public-profile snippets → `receive()` as SEED, Render cron, human review, statistics only; yield check `scripts/linkedin_snippet_yield.py`). Team dashboard `/admin` (`api/admin.py`, `domain/admin_stats.py`, web `components/admin/`) is for
accounts in `HELLOMYME_ADMIN_ACCOUNT_IDS`, counts only. Migration 0025 closes the Supabase Data API: every new table enables RLS
(`tests/test_data_api_lock.py`).

## Layout & commands
- `apps/api` — FastAPI + PostgreSQL 16, raw-SQL Alembic migrations (`migrations/versions`), pytest.
  `uv run ruff check . && uv run pytest` (needs `hellomyme_test` DB, see docker-compose).
- `apps/web` — Next.js App Router on :3001 (hmm-id dev server uses :3000). `npm run typecheck && npm run build`.
- `make db | migrate | import-preseed | api | web | test` from the repo root.
- Pre-seed data is NOT in the repo. Official PRE_SEED = `HELLOMYME_PreSeed_Career_Data_v1.3.xlsx`:
  `uv run hellomyme-import-preseed <file.xlsx> --retire v1.2` (version/as-of read from 00_README).
  v1.4 = add-on built from it for the other 4-year schools (`hellomyme-make-preseed`, `importer/generate.py`,
  `scripts/add-preseed-schools.ps1`; docs/10 §PRE_SEED v1.4). School list = public data in `hellomyme/reference/`
  (migration 0032, `scripts/build_kr_*.py`).
- v1.4 code paths: `domain/career_query.py` (CareerQuery engine, cohort v2), `domain/acquisition.py`
  + `api/acquisition.py` (`/acq/*` student/professional flows, login merge, `/acq/me`),
  web `components/AcquisitionFlow.tsx`. Legacy `/career/*` + snapshot engine remain for old drafts.
- SEED ingestion: input standard = the ingestion workbook (template v2.1, `ingest/sheet.py`,
  `hellomyme-ingest sheet <xlsx> --dry-run`, `scripts/ingest-sheet.ps1`); AI JSON path shares
  `pipeline.py`. Raw names stay, standardisation = aliases + mapping_queue; career order is derived
  from dates at query time; rows not reviewed are held. Legal review (docs/09 §9) gates production loads.

## Approved decisions (do not re-ask)
- Positioning: Nextpath is Hello My Me's first **acquisition / traffic-generator** product (like Toss
  remittance): free result → data → 튜브 micro-payments (cash cow) → data-driven connection to people
  "one step ahead" (helpers earn 튜브). Not a sub-layer of the FACE/Hello My Me journey.
- Stack Next.js + FastAPI + PostgreSQL; deploy Vercel (web) + managed FastAPI/Postgres.
- PRE_SEED is dev/UX/simulation only; production Career Map = SEED + VERIFIED (API refuses
  to start otherwise). Test deployment runs `HELLOMYME_ENV=staging` with SIMULATION labels.
- Credit unit is **튜브** (`*_tube` columns/fields), not MY. Paid cards (owner decision 2026-10-13, replaces
  "no real-money purchase in Phase 1"): one result card free, sign-up gives 1 튜브 (reward_v2), each further card
  1 튜브 = 990원 through Toss Payments (`pricing_policy` CARD_1, `domain/payments.py`, migration 0037, /terms).
  More cards (0038/0039, `acquisition.CARDS`, band metrics in `career_query.py`). Until a Toss key is set the checkout is the payment-intent test
  (`/pay/checkout`, provider TEST): nothing charged, the press is recorded, 1 튜브 gifted (PAYMENT_TEST_GIFT) and
  the person is told right after; the page never imitates a payment company.
- Kakao login only through HMM ID (`id.da-sh.io`, repo `YoungminDo/hmm-id`), backend-only
  docking; SP id `nextpath`, origin `https://nextpath.da-sh.io` (hmm-id PR #10 merged).
- Cohort: fallback 0 exact → 1 graduation ±window → 2 dimension fallback → 3 similarity top-K;
  thresholds/windows/rewards/costs live in policy tables, never in code.

## Non-negotiables
raw/source records append-only; unknown = NULL (never fabricate or repair data); immutable
credit ledger (corrections = REVERSAL); idempotent imports/rewards/unlocks/merges; small-cohort
and small-cell suppression; ACCOUNT ≠ PERSON; PII separated; PRE_SEED never identity-matched or
shown as a person/mentor; consent recorded before combining HMM identity with career data.
Interview phone numbers: own consent (INTERVIEW_CONTACT), optional, never logged, cleared on withdrawal.
Uploaded resumes/captures are never stored; overseas-transfer consent is recorded before the read; read rows
become career records only as the person confirmed them (before login: through the draft and the login merge);
the raw read is kept for statistics only with its own optional consent (0031, 3 years).
Preview/result screens carry no beta or example-data line (owner decision 2026-10-13); the landing FAQ
and landing footer still say results are computed from example data while records are collected.
Typed names the list does not know count the nearest group (`cohort_inputs`: region, similar majors), never
everyone of that year when the name gives a clue (docs/10 §숫자 아래 기준 표시).

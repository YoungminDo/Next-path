API = cd apps/api &&
WEB = cd apps/web &&

.PHONY: db migrate rollback test lint import-preseed api web

db:            ## start local PostgreSQL 16
	docker compose up -d postgres

migrate:
	$(API) uv run alembic upgrade head

rollback:      ## roll back every migration
	$(API) uv run alembic downgrade base

test:
	$(API) uv run ruff check . && uv run pytest
	$(WEB) npm run typecheck

import-preseed: ## make import-preseed CSV_DIR=/path/to/csv VERSION=v1.2 AS_OF=2026-10-07
	$(API) uv run hellomyme-import-preseed $(CSV_DIR) --dataset-version $(VERSION) --as-of $(AS_OF)

api:
	$(API) uv run uvicorn hellomyme.main:app --reload --port 8000

web:
	$(WEB) npm run dev

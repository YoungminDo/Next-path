# syntax=docker/dockerfile:1
# HELLOMYME Career API — portable image for any managed container host
# (Render, Railway, Fly.io, Cloud Run, AWS App Runner ...).
#
# Behind a TLS-intercepting proxy, pass its CA as an optional build secret:
#   docker build --secret id=extra_ca,src=/path/ca.crt .
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then \
      export PIP_CERT=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir "uv>=0.11,<0.12" \
    && uv sync --locked --no-dev --no-install-project
COPY hellomyme ./hellomyme
COPY migrations ./migrations
COPY alembic.ini ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export SSL_CERT_FILE=/run/secrets/extra_ca; fi; \
    uv sync --locked --no-dev

RUN useradd --create-home --uid 10001 app
USER app
ENV PATH="/app/.venv/bin:$PATH" PORT=8000
EXPOSE 8000
# Migrations run on start so every deploy brings the schema to head (idempotent).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn hellomyme.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]

# syntax=docker/dockerfile:1
#
# Multi-stage build for the AA Shinaka Digital Business Platform.
#   - assets:  compiles the Tailwind CSS bundle with Node
#   - runtime: installs Python dependencies with uv and runs Gunicorn
#
# Build:  docker build -f deploy/Dockerfile -t aa-shinaka:latest .
# Run:    see deploy/docker-compose.yml

# ---------------------------------------------------------------------------
# Stage 1 — static assets (Tailwind)
# ---------------------------------------------------------------------------
FROM node:20-slim AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY assets/css ./assets/css
COPY templates ./templates
RUN npm run build:css

# ---------------------------------------------------------------------------
# Stage 2 — Python runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/app/.venv/bin:$PATH"

# uv, pinned to a release for reproducible dependency installs.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /usr/local/bin/

WORKDIR /app

# Install Python dependencies first (cached until uv.lock changes).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Application code.
COPY . .
# Compiled Tailwind bundle from the assets stage.
COPY --from=assets /app/static/css/app.css ./static/css/app.css

# Run as an unprivileged user.
RUN useradd --create-home --uid 1001 app \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R app:app /app
USER app

EXPOSE 8000
# Probe with X-Forwarded-Proto: https so the production SSL redirect (which
# would otherwise bounce the probe to https://127.0.0.1) does not make the
# container look unhealthy. Honours Render's $PORT as well as the default.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import http.client,os,sys; c=http.client.HTTPConnection('127.0.0.1', int(os.environ.get('PORT','8000')), timeout=3); c.request('GET','/healthz/',headers={'X-Forwarded-Proto':'https'}); r=c.getresponse(); sys.exit(0 if r.status==200 else 1)"

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "deploy/gunicorn.conf.py"]

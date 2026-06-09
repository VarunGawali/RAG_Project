# ── Contract360 backend — FastAPI + uvicorn ───────────────────────────────────
#
# Build:
#   docker build -t contract360-api .
#
# Run (local, with a populated .env):
#   docker run --env-file .env -p 8000:8000 contract360-api
#
# For Azure Container Apps, set all env vars as Container App secrets/env vars
# in the portal or via `az containerapp update --set-env-vars ...`.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# System deps needed by pypdf / Pillow and gremlinpython websockets
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first so this layer is cached on code-only changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY app/ ./app/
COPY .env* ./

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

EXPOSE ${PORT}

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/health')" || exit 1

# Use uvicorn with 2 workers; scale via Container Apps replicas instead of processes
CMD ["sh", "-c", "uvicorn app.api:app --host 0.0.0.0 --port ${PORT} --workers 2"]

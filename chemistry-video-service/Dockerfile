FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install .

COPY assets ./assets

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app app \
    && mkdir -p /app/artifacts /app/data /app/downloads \
    && chown -R app:app /app

ENV APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000 \
    ARTIFACT_DIR=/app/artifacts \
    DATA_DIR=/app/data \
    ASSETS_DIR=/app/assets \
    JOB_REPOSITORY=sqlite \
    DATABASE_URL=sqlite:////app/data/app.db \
    TTS_PROVIDER=canonical_cache \
    ALLOW_PLACEHOLDER_AUDIO=false \
    GENERATION_MODE=real \
    WORKER_MODE=embedded

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/healthz || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

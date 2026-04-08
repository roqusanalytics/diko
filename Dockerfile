# Diko — multi-stage build: frontend (bun) + backend (python)

# Stage 1: Build frontend
FROM oven/bun:1 AS frontend-build
WORKDIR /app/frontend
COPY transkribas/frontend/package.json transkribas/frontend/bun.lock ./
RUN bun install --frozen-lockfile
COPY transkribas/frontend/ .
RUN bun run build

# Stage 2: Production
FROM python:3.13-slim
WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --no-cache-dir uv
COPY transkribas/backend/pyproject.toml transkribas/backend/uv.lock ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv pip install --system \
    fastapi uvicorn faster-whisper httpx sse-starlette yt-dlp

# Backend source
COPY transkribas/backend/ .

# Frontend static files (from build stage)
COPY --from=frontend-build /app/frontend/dist /app/static

# Data directory
RUN mkdir -p /data

# Environment
ENV PORT=8000
ENV DB_PATH=/data/diko.db
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Serve frontend from FastAPI + run backend
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

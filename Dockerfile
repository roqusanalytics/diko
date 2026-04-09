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

# System deps — split into separate layers to reduce peak memory
RUN apt-get update && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# Python deps — install without faster-whisper first (lighter), then whisper
RUN pip install --no-cache-dir \
    fastapi==0.135.3 \
    uvicorn[standard]==0.42.0 \
    httpx==0.28.1 \
    sse-starlette==3.3.4 \
    yt-dlp==2026.3.17 \
    pydantic

RUN pip install --no-cache-dir faster-whisper==1.2.1

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

CMD python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}

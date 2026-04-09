"""Residential transcript worker. Runs on a home Mac with residential IP.

Serves YouTube transcripts via youtube-transcript-api, bypassing
datacenter bot detection. Expose via Tailscale Funnel so Railway
can reach it.

Usage:
  cd diko/backend
  uv run python transcript_worker.py

Then in another terminal:
  tailscale funnel 8787

Set Railway env var:
  TRANSCRIPT_WORKER_URL=https://<your-machine>.tail<net>.ts.net:443
"""

import logging
import os

from fastapi import FastAPI, Request
from pydantic import BaseModel
from youtube_transcript_api import YouTubeTranscriptApi

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Diko Transcript Worker")

WORKER_TOKEN = os.environ.get("TRANSCRIPT_WORKER_TOKEN", "")


class TranscriptRequest(BaseModel):
    video_id: str
    language: str = "en"


@app.post("/transcript")
async def get_transcript(req: TranscriptRequest, request: Request):
    """Fetch YouTube transcript using residential IP."""
    # Auth check
    if WORKER_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {WORKER_TOKEN}":
            return {"ok": False, "error": "unauthorized"}

    try:
        ytt_api = YouTubeTranscriptApi()
        transcript = ytt_api.fetch(req.video_id, languages=[req.language, "en"])

        segments = []
        for entry in transcript:
            segments.append({
                "start": entry.start,
                "duration": entry.duration,
                "text": entry.text,
            })

        logger.info(f"Fetched {len(segments)} segments for {req.video_id}")
        return {"ok": True, "segments": segments}

    except Exception as e:
        logger.warning(f"Failed to fetch transcript for {req.video_id}: {e}")
        return {"ok": False, "error": str(e)}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8787)

"""TransKribas FastAPI backend. YouTube transcription with SSE progress streaming."""

import asyncio
import json
import logging
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

import database as db
import downloader
import exporter
import summarizer
import transcriber
from models import JobStatus, TranscriptRecord

logger = logging.getLogger(__name__)

# --- Job tracking ---

jobs: dict[str, dict] = {}  # job_id -> {status, progress, video_id, result, error, ...}
job_queue: asyncio.Queue = asyncio.Queue()

JOB_TTL_SECONDS = 1800  # 30 minutes
JOB_MAX_COUNT = 100


def _cleanup_jobs() -> None:
    """Remove expired jobs and enforce max count."""
    now = time.time()
    # Remove jobs older than TTL that are complete or errored
    expired = [
        jid for jid, j in jobs.items()
        if j["status"] in (JobStatus.COMPLETE, JobStatus.ERROR, "cancelled")
        and now - j.get("completed_at", now) > JOB_TTL_SECONDS
    ]
    for jid in expired:
        del jobs[jid]

    # Enforce max count by removing oldest completed jobs
    if len(jobs) > JOB_MAX_COUNT:
        completed = sorted(
            [(jid, j) for jid, j in jobs.items()
             if j["status"] in (JobStatus.COMPLETE, JobStatus.ERROR, "cancelled")],
            key=lambda x: x[1].get("completed_at", 0),
        )
        for jid, _ in completed[: len(jobs) - JOB_MAX_COUNT]:
            del jobs[jid]


async def process_jobs():
    """Background worker: process one transcription job at a time."""
    while True:
        job_id = await job_queue.get()
        job = jobs.get(job_id)
        if not job:
            continue

        try:
            # Check if cancelled before starting
            if job.get("cancelled"):
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                job_queue.task_done()
                continue

            job["status"] = JobStatus.PROCESSING
            url = job["url"]
            settings = db.get_settings()

            # Step 1: Download audio
            job["stage"] = "downloading"
            t0 = time.monotonic()
            download_result = await asyncio.to_thread(
                downloader.download_audio, url
            )
            job["video_id"] = download_result.video_id
            job["title"] = download_result.title
            job["duration"] = download_result.duration
            t_download = time.monotonic() - t0
            logger.info(f"Download completed in {t_download:.1f}s: {download_result.title}")

            # Check if cancelled after download
            if job.get("cancelled"):
                downloader.cleanup_audio(download_result.audio_path)
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                job_queue.task_done()
                continue

            # Check cache
            cached = db.get_transcript(download_result.video_id)
            if cached:
                job["status"] = JobStatus.COMPLETE
                job["result"] = cached
                job["completed_at"] = time.time()
                downloader.cleanup_audio(download_result.audio_path)
                job_queue.task_done()
                continue

            # Step 2: Transcribe
            job["stage"] = "transcribing"
            t1 = time.monotonic()

            def on_progress(pct: float):
                job["progress"] = pct

            transcription = await asyncio.to_thread(
                transcriber.transcribe,
                download_result.audio_path,
                settings.default_language or None,
                settings.whisper_model,
                on_progress,
            )
            t_transcribe = time.monotonic() - t1
            logger.info(f"Transcription completed in {t_transcribe:.1f}s: {transcription.language}")

            # Cleanup temp audio file
            downloader.cleanup_audio(download_result.audio_path)

            # Check if cancelled after transcription
            if job.get("cancelled"):
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                job_queue.task_done()
                continue

            # Model hint for non-EN languages
            model_hint = ""
            if transcription.language != "en" and settings.whisper_model == "small":
                model_hint = "non_en_small"

            # Step 3: Save to database
            record = TranscriptRecord(
                video_id=download_result.video_id,
                title=download_result.title,
                url=url,
                language=transcription.language,
                duration=transcription.duration,
                segments=transcription.segments,
                source="whisper",
                channel_name=download_result.channel_name,
                view_count=download_result.view_count,
                like_count=download_result.like_count,
            )
            db.save_transcript(record)
            job["result"] = record

            # Step 4: Generate summary
            job["stage"] = "summarizing"
            t2 = time.monotonic()
            try:
                if settings.openrouter_api_key:
                    db.update_summary_status(download_result.video_id, "pending")
                    full_text = " ".join(s.text for s in transcription.segments)
                    summary = await summarizer.summarize(
                        full_text,
                        settings.openrouter_api_key,
                        settings.openrouter_model,
                    )
                    db.update_summary(download_result.video_id, summary.text, "done")
                    record.summary = summary.text
                    record.summary_status = "done"
                    job["result"] = record
                else:
                    db.update_summary_status(download_result.video_id, "no_key")
                    record.summary_status = "no_key"
                    job["result"] = record
            except Exception as e:
                logger.warning(f"Summary failed for {download_result.video_id}: {e}")
                db.update_summary_status(download_result.video_id, "failed")
                record.summary_status = "failed"
                job["result"] = record

            t_summary = time.monotonic() - t2

            job["status"] = JobStatus.COMPLETE
            job["completed_at"] = time.time()
            job["timing"] = {
                "download_s": round(t_download, 1),
                "transcribe_s": round(t_transcribe, 1),
                "summary_s": round(t_summary, 1),
            }
            job["model_hint"] = model_hint
            logger.info(
                f"Job complete: download={t_download:.1f}s, "
                f"transcribe={t_transcribe:.1f}s, summary={t_summary:.1f}s"
            )

        except MemoryError:
            job["status"] = JobStatus.ERROR
            job["error"] = "Nepakanka atminties. Bandykite mažesnį Whisper modelį."
            job["completed_at"] = time.time()
            logger.error(f"MemoryError during transcription of {job.get('url', '?')}")

        except Exception as e:
            job["status"] = JobStatus.ERROR
            job["error"] = str(e)
            job["completed_at"] = time.time()

        job_queue.task_done()
        _cleanup_jobs()


# --- Media download job tracking ---

media_jobs: dict[str, dict] = {}
media_sem = asyncio.Semaphore(2)

MEDIA_TTL_SECONDS = 600  # 10 minutes
MEDIA_MAX_COUNT = 20


def _cleanup_media_jobs() -> None:
    """Remove expired media jobs and their temp files."""
    now = time.time()
    expired = [
        jid for jid, j in media_jobs.items()
        if j["status"] in ("complete", "error", "cancelled")
        and now - j.get("completed_at", now) > MEDIA_TTL_SECONDS
    ]
    for jid in expired:
        file_path = media_jobs[jid].get("file_path")
        if file_path:
            downloader.cleanup_media_dir(
                str(Path(file_path).parent)
            )
        del media_jobs[jid]

    if len(media_jobs) > MEDIA_MAX_COUNT:
        done = sorted(
            [
                (jid, j) for jid, j in media_jobs.items()
                if j["status"] in ("complete", "error")
            ],
            key=lambda x: x[1].get("completed_at", 0),
        )
        for jid, j in done[:len(media_jobs) - MEDIA_MAX_COUNT]:
            fp = j.get("file_path")
            if fp:
                downloader.cleanup_media_dir(
                    str(Path(fp).parent)
                )
            del media_jobs[jid]


async def process_media_download(job_id: str) -> None:
    """Process a single media download job under Semaphore."""
    job = media_jobs.get(job_id)
    if not job:
        return

    async with media_sem:
        try:
            if job.get("cancelled"):
                job["status"] = "cancelled"
                job["completed_at"] = time.time()
                return

            job["status"] = "processing"

            def on_progress(pct: float, stage: str) -> None:
                job["progress"] = pct
                job["stage"] = stage

            result = await asyncio.to_thread(
                downloader.download_media,
                job["url"],
                job["format"],
                job["quality"],
                job.get("start_time"),
                job.get("end_time"),
                on_progress,
            )

            job["status"] = "complete"
            job["file_path"] = result.file_path
            job["file_size"] = result.file_size
            job["title"] = result.title
            job["duration"] = result.duration
            job["completed_at"] = time.time()
            logger.info(
                f"Media download complete: {result.title} "
                f"({job['format']}, {result.file_size} bytes)"
            )

        except Exception as e:
            job["status"] = "error"
            job["error"] = str(e)
            job["completed_at"] = time.time()
            logger.error(f"Media download failed: {e}")

        _cleanup_media_jobs()


async def _media_janitor() -> None:
    """Periodically clean up expired media jobs (every 5 min)."""
    while True:
        await asyncio.sleep(300)
        _cleanup_media_jobs()


def _startup_cleanup() -> None:
    """Remove orphaned transkribas_media_ temp dirs on startup."""
    tmp = Path(tempfile.gettempdir())
    for d in tmp.glob("transkribas_media_*"):
        if d.is_dir():
            downloader.cleanup_media_dir(str(d))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.seed_default_models()
    _startup_cleanup()
    task = asyncio.create_task(process_jobs())
    janitor = asyncio.create_task(_media_janitor())
    yield
    task.cancel()
    janitor.cancel()


app = FastAPI(title="TransKribas", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Request/Response models ---

class TranscribeRequest(BaseModel):
    url: str
    force_whisper: bool = False


class SettingsRequest(BaseModel):
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    whisper_model: str = "small"
    default_language: str = ""
    media_format: str = "mp3"
    media_quality: str = "320"


class SaveModelRequest(BaseModel):
    model_id: str
    name: str


# --- Endpoints ---

@app.post("/api/transcribe")
async def transcribe_video(req: TranscribeRequest):
    """Submit a YouTube URL for transcription. Checks YouTube captions first."""
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL is required")

    # Try to extract video ID to check cache
    try:
        video_id = await asyncio.to_thread(downloader.extract_video_id, url)
    except Exception:
        raise HTTPException(400, "Invalid YouTube URL")

    # Check cache (skip if force_whisper to allow re-transcription)
    if not req.force_whisper:
        cached = db.get_transcript(video_id)
        if cached:
            return {
                "job_id": str(uuid.uuid4()),
                "video_id": video_id,
                "status": "complete",
                "transcript": _serialize_record(cached),
            }

    # Try YouTube captions first (unless force_whisper)
    if not req.force_whisper:
        settings = db.get_settings()
        lang = settings.default_language or "en"
        caption_result = await asyncio.to_thread(downloader.get_captions, url, lang)

        if caption_result:
            record = TranscriptRecord(
                video_id=caption_result["video_id"],
                title=caption_result["title"],
                url=url,
                language=lang,
                duration=caption_result["duration"],
                segments=caption_result["segments"],
                source=caption_result["source"],
                summary_status="pending",
                channel_name=caption_result["channel_name"],
                view_count=caption_result["view_count"],
                like_count=caption_result["like_count"],
            )
            db.save_transcript(record)

            # Try to generate summary in the background
            asyncio.create_task(_generate_summary_async(record.video_id, record.segments, settings))

            return {
                "job_id": str(uuid.uuid4()),
                "video_id": record.video_id,
                "status": "complete",
                "transcript": _serialize_record(record),
            }

    # No captions or force_whisper: queue for Whisper
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status": JobStatus.QUEUED,
        "progress": 0.0,
        "video_id": video_id,
        "url": url,
        "stage": "queued",
        "result": None,
        "error": None,
        "title": "",
        "cancelled": False,
        "completed_at": None,
        "timing": None,
        "model_hint": "",
    }
    await job_queue.put(job_id)

    return {
        "job_id": job_id,
        "video_id": video_id,
        "status": "queued",
        "queue_position": job_queue.qsize(),
    }


async def _generate_summary_async(video_id: str, segments, settings) -> None:
    """Generate summary in background for caption-sourced transcripts."""
    try:
        if settings.openrouter_api_key:
            full_text = " ".join(s.text for s in segments)
            summary = await summarizer.summarize(
                full_text,
                settings.openrouter_api_key,
                settings.openrouter_model,
            )
            db.update_summary(video_id, summary.text, "done")
        else:
            db.update_summary_status(video_id, "no_key")
    except Exception as e:
        logger.warning(f"Background summary failed for {video_id}: {e}")
        db.update_summary_status(video_id, "failed")


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancel a queued or in-progress job. Best-effort for Whisper jobs."""
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job["status"] in (JobStatus.COMPLETE, JobStatus.ERROR, "cancelled"):
        return {"status": "already_finished"}

    job["cancelled"] = True
    return {"status": "cancelling"}


@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: str, request: Request):
    """SSE stream for job progress. EventSource-compatible with auto-reconnect."""

    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            job = jobs.get(job_id)
            if not job:
                # Job evicted by TTL cleanup — check DB for completed transcript
                # The video_id might be in the URL params or we can't recover it
                yield {"event": "error", "data": json.dumps({"message": "Job not found"})}
                break

            status = job["status"]

            if status == "cancelled":
                yield {
                    "event": "cancelled",
                    "data": json.dumps({"message": "Atšaukta"}),
                }
                break

            elif status == JobStatus.QUEUED:
                yield {
                    "event": "queued",
                    "data": json.dumps({"queue_position": job_queue.qsize()}),
                }

            elif status == JobStatus.PROCESSING:
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "progress": round(job["progress"], 3),
                        "stage": job["stage"],
                        "title": job.get("title", ""),
                        "duration": job.get("duration", 0),
                    }),
                }

            elif status == JobStatus.COMPLETE:
                result = job["result"]
                data = _serialize_record(result)
                if job.get("timing"):
                    data["timing"] = job["timing"]
                if job.get("model_hint"):
                    data["model_hint"] = job["model_hint"]
                yield {
                    "event": "complete",
                    "data": json.dumps(data),
                }
                break

            elif status == JobStatus.ERROR:
                yield {
                    "event": "error",
                    "data": json.dumps({"message": job["error"]}),
                }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/transcripts/{video_id}")
async def get_transcript(video_id: str):
    """Get a cached transcript by video ID."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")
    return _serialize_record(record)


@app.delete("/api/transcripts/{video_id}")
async def delete_transcript(video_id: str):
    """Delete a transcript."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")
    db.delete_transcript(video_id)
    return {"status": "ok"}


# --- Batch / Playlist ---

class BatchRequest(BaseModel):
    urls: list[str]


@app.post("/api/transcribe/batch")
async def transcribe_batch(req: BatchRequest):
    """Submit multiple URLs for transcription. Returns list of job IDs."""
    results = []
    for url in req.urls:
        url = url.strip()
        if not url:
            continue
        try:
            video_id = await asyncio.to_thread(downloader.extract_video_id, url)
            cached = db.get_transcript(video_id)
            if cached:
                results.append({"url": url, "video_id": video_id, "status": "complete"})
                continue

            job_id = str(uuid.uuid4())
            jobs[job_id] = {
                "status": JobStatus.QUEUED,
                "progress": 0.0,
                "video_id": video_id,
                "url": url,
                "stage": "queued",
                "result": None,
                "error": None,
                "title": "",
                "cancelled": False,
                "completed_at": None,
                "timing": None,
                "model_hint": "",
            }
            await job_queue.put(job_id)
            results.append({"url": url, "video_id": video_id, "job_id": job_id, "status": "queued"})
        except Exception:
            results.append({"url": url, "status": "error", "error": "Invalid URL"})

    return {"jobs": results}


@app.post("/api/playlist")
async def extract_playlist(req: TranscribeRequest):
    """Extract video list from a YouTube playlist URL."""
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL is required")

    if not downloader.is_playlist_url(url):
        raise HTTPException(400, "Not a playlist URL")

    videos = await asyncio.to_thread(downloader.extract_playlist_urls, url)
    if not videos:
        raise HTTPException(400, "Could not extract playlist or playlist is empty")

    return {"videos": videos}


# --- Stats ---

@app.get("/api/stats")
async def get_stats():
    """Get transcript statistics."""
    return db.get_stats()


# --- Collections ---

class CollectionRequest(BaseModel):
    name: str


class CollectionItemRequest(BaseModel):
    video_id: str


@app.get("/api/collections")
async def list_collections():
    """List all collections with counts."""
    return {"collections": db.get_collections()}


@app.post("/api/collections")
async def create_collection(req: CollectionRequest):
    """Create a new collection."""
    try:
        cid = db.create_collection(req.name.strip())
        return {"id": cid, "name": req.name.strip()}
    except Exception:
        raise HTTPException(400, "Collection already exists")


@app.delete("/api/collections/{collection_id}")
async def delete_collection_endpoint(collection_id: int):
    """Delete a collection."""
    db.delete_collection(collection_id)
    return {"status": "ok"}


@app.get("/api/collections/{collection_id}/transcripts")
async def get_collection_transcripts(collection_id: int):
    """Get transcripts in a collection."""
    return {"items": db.get_collection_transcripts(collection_id)}


@app.post("/api/collections/{collection_id}/transcripts")
async def add_to_collection_endpoint(collection_id: int, req: CollectionItemRequest):
    """Add a transcript to a collection."""
    db.add_to_collection(req.video_id, collection_id)
    return {"status": "ok"}


@app.delete("/api/collections/{collection_id}/transcripts/{video_id}")
async def remove_from_collection_endpoint(collection_id: int, video_id: str):
    """Remove a transcript from a collection."""
    db.remove_from_collection(video_id, collection_id)
    return {"status": "ok"}


@app.get("/api/transcripts/{video_id}/collections")
async def get_transcript_collections_endpoint(video_id: str):
    """Get collections containing a transcript."""
    return {"collections": db.get_transcript_collections(video_id)}


# --- Summary Regeneration ---

@app.post("/api/transcripts/{video_id}/regenerate-summary")
async def regenerate_summary(video_id: str):
    """Regenerate summary for a transcript using the current LLM model."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")

    settings = db.get_settings()
    if not settings.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API raktas nenustatytas")

    db.update_summary_status(video_id, "pending")

    try:
        full_text = " ".join(s.text for s in record.segments)
        summary = await summarizer.summarize(
            full_text,
            settings.openrouter_api_key,
            settings.openrouter_model,
        )
        db.update_summary(video_id, summary.text, "done")
        return {"summary": summary.text, "status": "done"}
    except Exception as e:
        db.update_summary_status(video_id, "failed")
        raise HTTPException(500, f"Summary failed: {str(e)}")


# --- Additional Exports ---

@app.get("/api/transcripts/{video_id}/txt")
async def export_txt(video_id: str):
    """Export transcript as plain text."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")

    lines = [record.title, "=" * len(record.title), ""]
    if record.summary:
        lines.extend(["Santrauka:", record.summary, ""])
    lines.append("Transkripcija:")
    lines.append("")

    # Merge into paragraphs
    PAUSE = 2.0
    current: list[str] = []
    for i, seg in enumerate(record.segments):
        if i > 0 and seg.start - record.segments[i - 1].end >= PAUSE and current:
            lines.append(" ".join(current))
            lines.append("")
            current = []
        current.append(seg.text)
    if current:
        lines.append(" ".join(current))

    return Response(
        content="\n".join(lines),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{record.title}.txt"'},
    )


@app.get("/api/transcripts/{video_id}/json")
async def export_json(video_id: str):
    """Export transcript as JSON."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")

    data = {
        "video_id": record.video_id,
        "title": record.title,
        "url": record.url,
        "language": record.language,
        "duration": record.duration,
        "source": record.source,
        "summary": record.summary,
        "translated_text": record.translated_text,
        "created_at": record.created_at,
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in record.segments],
    }

    return Response(
        content=json.dumps(data, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{record.title}.json"'},
    )


@app.get("/api/search")
async def search(q: str = ""):
    """Full-text search across all transcripts."""
    if not q.strip():
        return {"results": []}
    results = db.search_transcripts(q.strip())
    return {"results": results}


@app.get("/api/library")
async def library():
    """List all transcribed videos."""
    return {"items": db.list_transcripts()}


@app.get("/api/settings")
async def get_settings():
    """Get current settings."""
    settings = db.get_settings()
    return {
        "openrouter_api_key": "***" if settings.openrouter_api_key else "",
        "openrouter_model": settings.openrouter_model,
        "whisper_model": settings.whisper_model,
        "default_language": settings.default_language,
        "media_format": settings.media_format,
        "media_quality": settings.media_quality,
    }


@app.put("/api/settings")
async def update_settings(req: SettingsRequest):
    """Update settings."""
    current = db.get_settings()

    # Don't overwrite API key with masked value
    if req.openrouter_api_key and req.openrouter_api_key != "***":
        current.openrouter_api_key = req.openrouter_api_key
    current.openrouter_model = req.openrouter_model
    current.whisper_model = req.whisper_model
    current.default_language = req.default_language
    current.media_format = req.media_format
    current.media_quality = req.media_quality

    db.save_settings(current)
    return {"status": "ok"}


# --- Models ---

_openrouter_models_cache: list[dict] | None = None
_openrouter_cache_time: float = 0


@app.get("/api/models/search")
async def search_openrouter_models(q: str = ""):
    """Search OpenRouter models. Caches the full list for 10 minutes."""
    global _openrouter_models_cache, _openrouter_cache_time

    # Fetch and cache OpenRouter model list
    if _openrouter_models_cache is None or (time.time() - _openrouter_cache_time) > 600:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://openrouter.ai/api/v1/models")
                res.raise_for_status()
                data = res.json()
                _openrouter_models_cache = [
                    {"id": m["id"], "name": m.get("name", m["id"])}
                    for m in data.get("data", [])
                ]
                _openrouter_cache_time = time.time()
        except Exception:
            _openrouter_models_cache = _openrouter_models_cache or []

    if not q.strip():
        return {"models": _openrouter_models_cache[:20]}

    query = q.lower()
    matches = [
        m for m in _openrouter_models_cache
        if query in m["id"].lower() or query in m["name"].lower()
    ]
    return {"models": matches[:20]}


@app.get("/api/models/saved")
async def get_saved_models():
    """Get user's saved model list."""
    return {"models": db.get_saved_models()}


@app.post("/api/models/saved")
async def save_model(req: SaveModelRequest):
    """Add a model to the saved list."""
    db.add_saved_model(req.model_id, req.name)
    return {"status": "ok"}


@app.delete("/api/models/saved/{model_id:path}")
async def delete_saved_model(model_id: str):
    """Remove a model from the saved list."""
    db.remove_saved_model(model_id)
    return {"status": "ok"}


@app.post("/api/models/saved/{model_id:path}/favorite")
async def favorite_model(model_id: str):
    """Set a model as the favorite/default."""
    db.set_favorite_model(model_id)
    return {"status": "ok"}


@app.get("/api/transcripts/{video_id}/srt")
async def export_srt(video_id: str):
    """Export transcript as SRT subtitle file."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")
    srt_content = exporter.to_srt(record.segments)
    return Response(
        content=srt_content,
        media_type="text/srt",
        headers={"Content-Disposition": f'attachment; filename="{record.title}.srt"'},
    )


@app.get("/api/transcripts/{video_id}/pdf")
async def export_pdf(video_id: str):
    """Export transcript as PDF. Requires weasyprint."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")
    try:
        from weasyprint import HTML
        html_content = exporter.to_pdf_html(record.title, record.segments, record.summary)
        pdf_bytes = HTML(string=html_content).write_pdf()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{record.title}.pdf"'},
        )
    except ImportError:
        raise HTTPException(501, "PDF export unavailable. Install weasyprint: pip install weasyprint")


@app.post("/api/transcripts/{video_id}/translate")
async def translate_transcript(video_id: str):
    """Translate transcript text to Lithuanian using OpenRouter LLM."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")

    settings = db.get_settings()
    if not settings.openrouter_api_key:
        raise HTTPException(400, "OpenRouter API raktas nenustatytas")

    full_text = " ".join(s.text for s in record.segments)

    # Chunk long texts (~48k chars max per request)
    chunks = []
    if len(full_text) > 40000:
        words = full_text.split()
        chunk = []
        chunk_len = 0
        for w in words:
            chunk.append(w)
            chunk_len += len(w) + 1
            if chunk_len > 38000:
                chunks.append(" ".join(chunk))
                chunk = []
                chunk_len = 0
        if chunk:
            chunks.append(" ".join(chunk))
    else:
        chunks = [full_text]

    translated_parts = []
    for chunk in chunks:
        import httpx
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openrouter_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Esi profesionalus vertėjas. Išversk šį tekstą į lietuvių kalbą. "
                                "Išlaikyk originalią prasmę ir toną. Formatuok tekstą tvarkingais "
                                "sakiniais ir pastraipomis, kad būtų lengva skaityti kaip knygą. "
                                "Naudok taisyklingą lietuvių kalbos gramatiką ir skyrybą. "
                                "Grąžink tik vertimą, be jokių komentarų ar paaiškinimų."
                            ),
                        },
                        {"role": "user", "content": chunk},
                    ],
                    "max_tokens": 4096,
                },
            )
            response.raise_for_status()
            data = response.json()
            translated_parts.append(data["choices"][0]["message"]["content"])

    translated = "\n\n".join(translated_parts)
    db.update_translation(video_id, translated)

    return {"translated_text": translated}


@app.get("/api/transcripts/{video_id}/md")
async def export_markdown(video_id: str):
    """Export transcript as Markdown file."""
    record = db.get_transcript(video_id)
    if not record:
        raise HTTPException(404, "Transcript not found")

    lines = [f"# {record.title}\n"]
    lines.append(f"**Šaltinis:** {record.url}  ")
    lines.append(f"**Kalba:** {record.language.upper()}  ")

    minutes = int(record.duration // 60)
    seconds = int(record.duration % 60)
    lines.append(f"**Trukmė:** {minutes}:{seconds:02d}  ")
    lines.append(f"**Šaltinis:** {'YouTube subtitrai' if 'youtube' in record.source else 'Whisper AI'}  ")
    lines.append("")

    if record.summary:
        lines.append("## Santrauka\n")
        lines.append(record.summary)
        lines.append("")

    if record.translated_text:
        lines.append("## Vertimas (LT)\n")
        lines.append(record.translated_text)
        lines.append("")

    # Full text as paragraphs (merged by pauses)
    lines.append("## Transkripcija\n")
    PAUSE_THRESHOLD = 2.0
    paragraphs: list[str] = []
    current_parts: list[str] = []

    for i, seg in enumerate(record.segments):
        if i > 0:
            gap = seg.start - record.segments[i - 1].end
            if gap >= PAUSE_THRESHOLD and current_parts:
                paragraphs.append(" ".join(current_parts))
                current_parts = []
        current_parts.append(seg.text)

    if current_parts:
        paragraphs.append(" ".join(current_parts))

    lines.append("\n\n".join(paragraphs))
    lines.append("")

    # Timestamped segments at the end
    lines.append("## Subtitrai su laiko žymomis\n")
    for seg in record.segments:
        m = int(seg.start // 60)
        s = int(seg.start % 60)
        lines.append(f"**[{m}:{s:02d}]** {seg.text}  ")
    lines.append("")

    md_content = "\n".join(lines)

    return Response(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{record.title}.md"'},
    )


# --- Media Download ---

class MediaDownloadRequest(BaseModel):
    url: str = ""
    video_id: str = ""
    format: str = "mp3"
    quality: str = "320"
    start_time: float | None = None
    end_time: float | None = None


@app.post("/api/media/download")
async def start_media_download(req: MediaDownloadRequest):
    """Start a media download job. Returns job_id for SSE tracking."""
    # Resolve URL from video_id if needed
    url = req.url.strip()
    if not url and req.video_id:
        record = db.get_transcript(req.video_id)
        if not record:
            raise HTTPException(404, "Įrašas nerastas")
        url = record.url

    if not url:
        raise HTTPException(400, "URL arba video_id privalomas")

    # Validate format
    valid = downloader.AUDIO_FORMATS | downloader.VIDEO_FORMATS
    if req.format not in valid:
        raise HTTPException(
            400, f"Neteisingas formatas: {req.format}"
        )

    # Validate trim range
    if req.start_time is not None and req.end_time is not None:
        if req.start_time >= req.end_time:
            raise HTTPException(
                400, "Pradžia turi būti mažesnė nei pabaiga"
            )
        if req.end_time - req.start_time < 1:
            raise HTTPException(
                400, "Minimalus intervalas: 1 sekundė"
            )

    # Validate URL is YouTube
    try:
        video_id = await asyncio.to_thread(
            downloader.extract_video_id, url
        )
    except Exception:
        raise HTTPException(400, "Netinkama YouTube nuoroda")

    job_id = str(uuid.uuid4())
    media_jobs[job_id] = {
        "status": "queued",
        "progress": 0.0,
        "stage": "queued",
        "url": url,
        "video_id": video_id,
        "format": req.format,
        "quality": req.quality,
        "start_time": req.start_time,
        "end_time": req.end_time,
        "title": "",
        "duration": 0,
        "file_path": None,
        "file_size": 0,
        "error": None,
        "cancelled": False,
        "completed_at": None,
    }

    asyncio.create_task(process_media_download(job_id))

    return {"job_id": job_id, "video_id": video_id}


@app.get("/api/media/{job_id}/stream")
async def media_job_stream(job_id: str, request: Request):
    """SSE stream for media download progress."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break

            job = media_jobs.get(job_id)
            if not job:
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"message": "Job not found"}
                    ),
                }
                break

            status = job["status"]

            if status == "cancelled":
                yield {
                    "event": "cancelled",
                    "data": json.dumps(
                        {"message": "Atšaukta"}
                    ),
                }
                break

            elif status == "queued":
                yield {
                    "event": "queued",
                    "data": json.dumps({"status": "queued"}),
                }

            elif status == "processing":
                yield {
                    "event": "progress",
                    "data": json.dumps({
                        "progress": round(
                            job["progress"], 3
                        ),
                        "stage": job["stage"],
                        "title": job.get("title", ""),
                    }),
                }

            elif status == "complete":
                yield {
                    "event": "complete",
                    "data": json.dumps({
                        "job_id": job_id,
                        "title": job.get("title", ""),
                        "format": job["format"],
                        "file_size": job.get(
                            "file_size", 0
                        ),
                    }),
                }
                break

            elif status == "error":
                yield {
                    "event": "error",
                    "data": json.dumps(
                        {"message": job["error"]}
                    ),
                }
                break

            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/api/media/{job_id}/file")
async def serve_media_file(job_id: str):
    """Serve a completed media download file."""
    job = media_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    if job["status"] == "processing":
        raise HTTPException(
            409, "Atsisiuntimas dar vyksta"
        )

    if job["status"] == "error":
        raise HTTPException(
            400, job.get("error", "Klaida")
        )

    file_path = job.get("file_path")
    if not file_path or not Path(file_path).exists():
        raise HTTPException(
            410, "Failas nebepasiekiamas"
        )

    path = Path(file_path)
    title = job.get("title", "download")
    # Sanitize filename
    safe_title = "".join(
        c for c in title
        if c.isalnum() or c in " ._-"
    ).strip() or "download"
    filename = f"{safe_title}.{job['format']}"

    media_types = {
        "mp3": "audio/mpeg",
        "m4a": "audio/mp4",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "mp4": "video/mp4",
        "webm": "video/webm",
    }
    media_type = media_types.get(
        job["format"], "application/octet-stream"
    )

    def file_iterator():
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                yield chunk

    return StreamingResponse(
        file_iterator(),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            ),
            "Content-Length": str(path.stat().st_size),
        },
    )


@app.post("/api/media/{job_id}/cancel")
async def cancel_media_download(job_id: str):
    """Cancel a media download job."""
    job = media_jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job["status"] in ("complete", "error", "cancelled"):
        return {"status": "already_finished"}
    job["cancelled"] = True
    return {"status": "cancelling"}


# --- Helpers ---

def _serialize_record(record: TranscriptRecord) -> dict:
    """Convert a TranscriptRecord to a JSON-serializable dict."""
    return {
        "video_id": record.video_id,
        "title": record.title,
        "url": record.url,
        "language": record.language,
        "duration": record.duration,
        "summary": record.summary,
        "summary_status": record.summary_status,
        "source": record.source,
        "translated_text": record.translated_text,
        "channel_name": record.channel_name,
        "view_count": record.view_count,
        "like_count": record.like_count,
        "created_at": record.created_at,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text}
            for s in record.segments
        ],
    }

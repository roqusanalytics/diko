"""Tests for FastAPI endpoints."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import database as db
from models import DownloadResult, Settings, TranscriptRecord, TranscriptSegment


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    with patch.object(db, "DB_PATH", tmp_path / "test.db"):
        db.init_db()
        yield


@pytest.fixture
def sample_record() -> TranscriptRecord:
    return TranscriptRecord(
        video_id="dQw4w9WgXcQ",
        title="Rick Astley - Never Gonna Give You Up",
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        language="en",
        duration=212.0,
        segments=[
            TranscriptSegment(start=0.0, end=3.0, text="We're no strangers to love"),
            TranscriptSegment(start=3.0, end=7.0, text="You know the rules and so do I"),
        ],
        summary="A classic 1987 pop song about love.",
        summary_status="done",
        source="whisper",
    )


@pytest.fixture
def yt_caption_record() -> TranscriptRecord:
    return TranscriptRecord(
        video_id="dQw4w9WgXcQ",
        title="Rick Astley - Never Gonna Give You Up",
        url="https://youtube.com/watch?v=dQw4w9WgXcQ",
        language="en",
        duration=212.0,
        segments=[
            TranscriptSegment(start=0.0, end=3.0, text="We're no strangers to love"),
        ],
        source="youtube_auto",
        summary_status="no_key",
    )


@pytest_asyncio.fixture
async def client():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --- Transcript endpoints ---

@pytest.mark.asyncio
async def test_get_transcript_cached(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/transcripts/dQw4w9WgXcQ")
    assert res.status_code == 200
    data = res.json()
    assert data["video_id"] == "dQw4w9WgXcQ"
    assert len(data["segments"]) == 2


@pytest.mark.asyncio
async def test_get_transcript_not_found(client):
    res = await client.get("/api/transcripts/nonexistent")
    assert res.status_code == 404


# --- Search ---

@pytest.mark.asyncio
async def test_search_with_results(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/search?q=strangers")
    assert res.status_code == 200
    data = res.json()
    assert len(data["results"]) >= 1


@pytest.mark.asyncio
async def test_search_empty_query(client):
    res = await client.get("/api/search?q=")
    assert res.status_code == 200
    assert res.json()["results"] == []


# --- Library ---

@pytest.mark.asyncio
async def test_library_empty(client):
    res = await client.get("/api/library")
    assert res.status_code == 200
    assert res.json()["items"] == []


@pytest.mark.asyncio
async def test_library_with_items(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/library")
    assert res.status_code == 200
    assert len(res.json()["items"]) == 1


# --- Settings ---

@pytest.mark.asyncio
async def test_get_settings_default(client):
    res = await client.get("/api/settings")
    assert res.status_code == 200
    data = res.json()
    assert data["whisper_model"] == "small"


@pytest.mark.asyncio
async def test_update_settings(client):
    res = await client.put("/api/settings", json={
        "openrouter_api_key": "test-key",
        "openrouter_model": "openai/gpt-4o-mini",
        "whisper_model": "medium",
        "default_language": "lt",
    })
    assert res.status_code == 200
    res2 = await client.get("/api/settings")
    data = res2.json()
    assert data["whisper_model"] == "medium"
    assert data["openrouter_api_key"] == "***"  # Masked


# --- Transcribe ---

@pytest.mark.asyncio
async def test_transcribe_cached(client, sample_record):
    db.save_transcript(sample_record)
    with patch("downloader.extract_video_id", return_value="dQw4w9WgXcQ"):
        res = await client.post("/api/transcribe", json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "complete"
    assert data["transcript"]["video_id"] == "dQw4w9WgXcQ"


@pytest.mark.asyncio
async def test_transcribe_empty_url(client):
    res = await client.post("/api/transcribe", json={"url": ""})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_transcribe_invalid_url(client):
    with patch("downloader.extract_video_id", side_effect=Exception("Not a valid URL")):
        res = await client.post("/api/transcribe", json={"url": "not-a-url"})
    assert res.status_code == 400


# --- Export ---

@pytest.mark.asyncio
async def test_export_srt(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/transcripts/dQw4w9WgXcQ/srt")
    assert res.status_code == 200
    assert "00:00:00,000 --> 00:00:03,000" in res.text
    assert "We're no strangers to love" in res.text


# --- Source and Summary Status ---

@pytest.mark.asyncio
async def test_transcript_includes_source(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/transcripts/dQw4w9WgXcQ")
    assert res.status_code == 200
    data = res.json()
    assert data["source"] == "whisper"


@pytest.mark.asyncio
async def test_transcript_includes_summary_status(client, sample_record):
    db.save_transcript(sample_record)
    res = await client.get("/api/transcripts/dQw4w9WgXcQ")
    data = res.json()
    assert data["summary_status"] == "done"


@pytest.mark.asyncio
async def test_yt_caption_source(client, yt_caption_record):
    db.save_transcript(yt_caption_record)
    res = await client.get("/api/transcripts/dQw4w9WgXcQ")
    data = res.json()
    assert data["source"] == "youtube_auto"
    assert data["summary_status"] == "no_key"


# --- Force Whisper ---

@pytest.mark.asyncio
async def test_force_whisper_bypasses_cache(client, sample_record):
    """force_whisper=true should not return cached result."""
    db.save_transcript(sample_record)
    with patch("downloader.extract_video_id", return_value="dQw4w9WgXcQ"), \
         patch("downloader.get_captions", return_value=None):
        res = await client.post("/api/transcribe", json={
            "url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "force_whisper": True,
        })
    assert res.status_code == 200
    data = res.json()
    # Should be queued for Whisper, not return cached
    assert data["status"] == "queued"


# --- Caption Path ---

@pytest.mark.asyncio
async def test_transcribe_with_captions(client):
    """When YouTube captions are available, should return immediately."""
    caption_segments = [
        TranscriptSegment(start=0.0, end=3.0, text="Hello from captions"),
    ]
    caption_result = {
        "segments": caption_segments, "source": "youtube_manual", "video_id": "testVID",
        "title": "Test Title", "duration": 120.0, "channel_name": "Test Channel",
        "view_count": 1000, "like_count": 50,
    }

    with patch("downloader.extract_video_id", return_value="testVID"), \
         patch("downloader.get_captions", return_value=caption_result), \
         patch("main._generate_summary_async", return_value=None):
        res = await client.post("/api/transcribe", json={"url": "https://youtube.com/watch?v=testVID"})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "complete"
    assert data["transcript"]["source"] == "youtube_manual"
    assert data["transcript"]["segments"][0]["text"] == "Hello from captions"


@pytest.mark.asyncio
async def test_transcribe_no_captions_queues_whisper(client):
    """When no captions, should queue for Whisper."""
    with patch("downloader.extract_video_id", return_value="noCapVID"), \
         patch("downloader.get_captions", return_value=None):
        res = await client.post("/api/transcribe", json={"url": "https://youtube.com/watch?v=noCapVID"})

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"


# --- Cancel ---

@pytest.mark.asyncio
async def test_cancel_nonexistent_job(client):
    res = await client.post("/api/jobs/nonexistent/cancel")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_cancel_queued_job(client):
    """Cancelling a queued job should work."""
    from main import jobs, JobStatus
    job_id = "test-cancel-123"
    jobs[job_id] = {
        "status": JobStatus.QUEUED,
        "progress": 0.0,
        "video_id": "test",
        "url": "https://youtube.com/watch?v=test",
        "stage": "queued",
        "result": None,
        "error": None,
        "title": "",
        "cancelled": False,
        "completed_at": None,
        "timing": None,
        "model_hint": "",
    }
    res = await client.post(f"/api/jobs/{job_id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelling"
    assert jobs[job_id]["cancelled"] is True
    # Cleanup
    del jobs[job_id]

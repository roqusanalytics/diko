"""Tests for residential worker proxy integration."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import database as db
import downloader


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    with patch.object(db, "DB_PATH", tmp_path / "test.db"):
        db.init_db()
        yield


@pytest.fixture
async def client():
    from main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def test_extract_video_id_uses_worker(monkeypatch):
    monkeypatch.setenv("YTDLP_WORKER_URL", "https://worker.example")

    with patch("downloader._worker_json", return_value={"video_id": "dQw4w9WgXcQ"}) as mock_json:
        assert downloader.extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    mock_json.assert_called_once_with(
        "/internal/youtube/extract-video-id",
        {"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
    )


def test_get_captions_uses_worker(monkeypatch):
    monkeypatch.setenv("YTDLP_WORKER_URL", "https://worker.example")

    with patch(
        "downloader._worker_json",
        return_value={
            "ok": True,
            "video_id": "abc123def45",
            "title": "Test title",
            "duration": 12.5,
            "channel_name": "Channel",
            "view_count": 10,
            "like_count": 2,
            "source": "youtube_auto",
            "segments": [{"start": 0.0, "end": 1.0, "text": "Hello"}],
        },
    ):
        result = downloader.get_captions("https://youtu.be/abc123def45", "lt")

    assert result is not None
    assert result["video_id"] == "abc123def45"
    assert result["source"] == "youtube_auto"
    assert result["segments"][0].text == "Hello"


def test_download_audio_uses_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WORKER_URL", "https://worker.example")
    audio_path = tmp_path / "abc123def45.m4a"
    audio_path.write_bytes(b"audio")

    with patch(
        "downloader._worker_download",
        return_value=(
            audio_path,
            {
                "video_id": "abc123def45",
                "title": "Remote audio",
                "duration": 22.0,
                "channel_name": "Channel",
                "view_count": 100,
                "like_count": 5,
            },
        ),
    ):
        result = downloader.download_audio("https://youtu.be/abc123def45")

    assert result.audio_path == str(audio_path)
    assert result.title == "Remote audio"
    assert result.duration == 22.0


def test_download_media_uses_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("YTDLP_WORKER_URL", "https://worker.example")
    media_path = tmp_path / "abc123def45.mp3"
    media_path.write_bytes(b"media")

    with patch(
        "downloader._worker_download",
        return_value=(
            media_path,
            {
                "video_id": "abc123def45",
                "title": "Remote media",
                "duration": 33.0,
                "format": "mp3",
                "file_size": 5,
            },
        ),
    ):
        result = downloader.download_media("https://youtu.be/abc123def45", fmt="mp3")

    assert result.file_path == str(media_path)
    assert result.title == "Remote media"
    assert result.file_size == 5


@pytest.mark.asyncio
async def test_internal_worker_endpoint_requires_token(client, monkeypatch):
    monkeypatch.setenv("YTDLP_WORKER_TOKEN", "secret")

    res = await client.post(
        "/internal/youtube/extract-video-id",
        json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
    )
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_internal_worker_extract_video_id(client, monkeypatch):
    monkeypatch.setenv("YTDLP_WORKER_TOKEN", "secret")

    with patch("downloader.extract_video_id_local", return_value="dQw4w9WgXcQ"):
        res = await client.post(
            "/internal/youtube/extract-video-id",
            json={"url": "https://youtube.com/watch?v=dQw4w9WgXcQ"},
            headers={"Authorization": "Bearer secret"},
        )

    assert res.status_code == 200
    assert res.json()["video_id"] == "dQw4w9WgXcQ"

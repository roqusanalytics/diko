"""Tests for media download endpoints and downloader functions."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from httpx import ASGITransport, AsyncClient

sys.path.insert(0, str(Path(__file__).parent.parent))

import database as db
from models import (
    MediaDownloadResult,
    Settings,
    TranscriptRecord,
    TranscriptSegment,
)
import downloader


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
            TranscriptSegment(
                start=0.0, end=3.0,
                text="We're no strangers to love",
            ),
        ],
        source="whisper",
    )


# --- downloader._build_format_string tests ---


class TestBuildFormatString:
    def test_mp3_320(self):
        fmt, pp = downloader._build_format_string("mp3", "320")
        assert fmt == "bestaudio[ext=m4a]/bestaudio"
        assert len(pp) == 1
        assert pp[0]["key"] == "FFmpegExtractAudio"
        assert pp[0]["preferredcodec"] == "mp3"
        assert pp[0]["preferredquality"] == "320"

    def test_mp3_128(self):
        _, pp = downloader._build_format_string("mp3", "128")
        assert pp[0]["preferredquality"] == "128"

    def test_m4a_no_conversion(self):
        fmt, pp = downloader._build_format_string("m4a", "")
        assert fmt == "bestaudio[ext=m4a]/bestaudio"
        assert pp == []

    def test_wav_no_quality(self):
        _, pp = downloader._build_format_string("wav", "320")
        assert pp[0]["preferredcodec"] == "wav"
        assert "preferredquality" not in pp[0]

    def test_flac_no_quality(self):
        _, pp = downloader._build_format_string("flac", "")
        assert pp[0]["preferredcodec"] == "flac"
        assert "preferredquality" not in pp[0]

    def test_ogg_with_bitrate(self):
        _, pp = downloader._build_format_string("ogg", "192")
        assert pp[0]["preferredcodec"] == "vorbis"
        assert pp[0]["preferredquality"] == "192"

    def test_mp4_1080p(self):
        fmt, pp = downloader._build_format_string("mp4", "1080")
        assert "[height<=1080]" in fmt
        assert "[ext=mp4]" in fmt
        assert pp == []

    def test_mp4_best(self):
        fmt, pp = downloader._build_format_string("mp4", "best")
        assert "[height<=" not in fmt
        assert pp == []

    def test_mp4_720(self):
        fmt, _ = downloader._build_format_string("mp4", "720")
        assert "[height<=720]" in fmt

    def test_webm_720(self):
        fmt, _ = downloader._build_format_string("webm", "720")
        assert "[height<=720]" in fmt
        assert "[ext=webm]" in fmt

    def test_mp4_360(self):
        fmt, _ = downloader._build_format_string("mp4", "360")
        assert "[height<=360]" in fmt


class TestDownloadMediaValidation:
    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Unsupported format"):
            downloader.download_media(
                "https://youtube.com/watch?v=x", fmt="avi"
            )


class TestFindOutputFile:
    def test_finds_exact_format(self, tmp_path):
        (tmp_path / "video.mp3").touch()
        result = downloader._find_output_file(tmp_path, "mp3")
        assert result is not None
        assert result.suffix == ".mp3"

    def test_finds_fallback(self, tmp_path):
        (tmp_path / "video.m4a").touch()
        result = downloader._find_output_file(tmp_path, "mp3")
        assert result is not None
        assert result.suffix == ".m4a"

    def test_returns_none_empty(self, tmp_path):
        result = downloader._find_output_file(tmp_path, "mp3")
        assert result is None


class TestCleanupMediaDir:
    def test_cleans_media_dir(self, tmp_path):
        d = tmp_path / "diko_media_abc"
        d.mkdir()
        (d / "file.mp3").touch()
        downloader.cleanup_media_dir(str(d))
        assert not d.exists()

    def test_ignores_non_media_dir(self, tmp_path):
        d = tmp_path / "other_dir"
        d.mkdir()
        (d / "file.mp3").touch()
        downloader.cleanup_media_dir(str(d))
        assert d.exists()


# --- API endpoint tests ---


@pytest.fixture
def app():
    from main import app
    return app


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as c:
        yield c


class TestMediaDownloadEndpoint:
    @pytest.mark.asyncio
    async def test_missing_url_and_video_id(self, client):
        res = await client.post(
            "/api/media/download",
            json={"format": "mp3"},
        )
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_format(self, client):
        res = await client.post(
            "/api/media/download",
            json={"url": "https://youtube.com/watch?v=x", "format": "avi"},
        )
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_trim_range(self, client):
        res = await client.post(
            "/api/media/download",
            json={
                "url": "https://youtube.com/watch?v=x",
                "format": "mp3",
                "start_time": 10.0,
                "end_time": 5.0,
            },
        )
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_trim_too_short(self, client):
        res = await client.post(
            "/api/media/download",
            json={
                "url": "https://youtube.com/watch?v=x",
                "format": "mp3",
                "start_time": 5.0,
                "end_time": 5.5,
            },
        )
        assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_youtube_url(self, client):
        with patch(
            "downloader.extract_video_id",
            side_effect=Exception("bad url"),
        ):
            res = await client.post(
                "/api/media/download",
                json={
                    "url": "https://example.com/not-youtube",
                    "format": "mp3",
                },
            )
            assert res.status_code == 400

    @pytest.mark.asyncio
    async def test_video_id_lookup(self, client, sample_record):
        db.save_transcript(sample_record)
        with patch(
            "downloader.extract_video_id",
            return_value="dQw4w9WgXcQ",
        ):
            res = await client.post(
                "/api/media/download",
                json={
                    "video_id": "dQw4w9WgXcQ",
                    "format": "mp3",
                },
            )
            assert res.status_code == 200
            data = res.json()
            assert "job_id" in data

    @pytest.mark.asyncio
    async def test_video_id_not_found(self, client):
        res = await client.post(
            "/api/media/download",
            json={"video_id": "nonexistent", "format": "mp3"},
        )
        assert res.status_code == 404


class TestMediaFileEndpoint:
    @pytest.mark.asyncio
    async def test_job_not_found(self, client):
        res = await client.get("/api/media/fake-id/file")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_file_gone(self, client):
        from main import media_jobs
        media_jobs["test-job"] = {
            "status": "complete",
            "file_path": "/nonexistent/file.mp3",
            "format": "mp3",
            "title": "Test",
            "error": None,
            "completed_at": 0,
        }
        res = await client.get("/api/media/test-job/file")
        assert res.status_code == 410
        del media_jobs["test-job"]

    @pytest.mark.asyncio
    async def test_job_still_processing(self, client):
        from main import media_jobs
        media_jobs["test-job-2"] = {
            "status": "processing",
            "format": "mp3",
            "title": "Test",
            "file_path": None,
            "error": None,
            "completed_at": None,
        }
        res = await client.get("/api/media/test-job-2/file")
        assert res.status_code == 409
        del media_jobs["test-job-2"]

    @pytest.mark.asyncio
    async def test_serve_file(self, client, tmp_path):
        test_file = tmp_path / "test.mp3"
        test_file.write_bytes(b"fake mp3 data")

        from main import media_jobs
        media_jobs["serve-test"] = {
            "status": "complete",
            "file_path": str(test_file),
            "format": "mp3",
            "title": "Test Song",
            "error": None,
            "completed_at": 0,
        }
        res = await client.get("/api/media/serve-test/file")
        assert res.status_code == 200
        assert res.headers["content-type"] == "audio/mpeg"
        assert "Test Song.mp3" in res.headers["content-disposition"]
        assert res.content == b"fake mp3 data"
        del media_jobs["serve-test"]


class TestMediaCancelEndpoint:
    @pytest.mark.asyncio
    async def test_cancel_not_found(self, client):
        res = await client.post("/api/media/fake/cancel")
        assert res.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_running(self, client):
        from main import media_jobs
        media_jobs["cancel-test"] = {
            "status": "processing",
            "cancelled": False,
            "completed_at": None,
        }
        res = await client.post("/api/media/cancel-test/cancel")
        assert res.status_code == 200
        assert media_jobs["cancel-test"]["cancelled"] is True
        del media_jobs["cancel-test"]

    @pytest.mark.asyncio
    async def test_cancel_already_done(self, client):
        from main import media_jobs
        media_jobs["done-test"] = {
            "status": "complete",
            "cancelled": False,
            "completed_at": 0,
        }
        res = await client.post("/api/media/done-test/cancel")
        assert res.json()["status"] == "already_finished"
        del media_jobs["done-test"]

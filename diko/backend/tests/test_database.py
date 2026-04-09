"""Tests for database.py: CRUD, FTS5 search, settings."""

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import database as db
from models import Settings, TranscriptRecord, TranscriptSegment


@pytest.fixture(autouse=True)
def mock_keychain():
    """Mock Keychain in tests — in-memory store."""
    import keychain
    _store = {}
    with patch.object(keychain, "get_secret", side_effect=lambda k: _store.get(k)), \
         patch.object(keychain, "set_secret", side_effect=lambda k, v: _store.update({k: v}) or True), \
         patch.object(keychain, "migrate_from_db", return_value=False):
        yield


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    """Use a temporary database for each test."""
    test_db = tmp_path / "test.db"
    with patch.object(db, "DB_PATH", test_db):
        db.init_db()
        yield


def _make_record(video_id="abc123", title="Test Video") -> TranscriptRecord:
    return TranscriptRecord(
        video_id=video_id,
        title=title,
        url=f"https://youtube.com/watch?v={video_id}",
        language="en",
        duration=120.0,
        segments=[
            TranscriptSegment(start=0.0, end=3.0, text="Hello world"),
            TranscriptSegment(start=3.0, end=6.0, text="This is a test"),
            TranscriptSegment(start=6.0, end=10.0, text="Machine learning is interesting"),
        ],
        summary="A test video about machine learning.",
    )


# --- CRUD Tests ---

def test_save_and_get_transcript():
    record = _make_record()
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result is not None
    assert result.video_id == "abc123"
    assert result.title == "Test Video"
    assert len(result.segments) == 3
    assert result.segments[0].text == "Hello world"


def test_get_nonexistent_transcript():
    result = db.get_transcript("nonexistent")
    assert result is None


def test_save_duplicate_updates():
    record = _make_record()
    db.save_transcript(record)
    record.summary = "Updated summary"
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result.summary == "Updated summary"


def test_list_transcripts():
    db.save_transcript(_make_record("vid1", "First Video"))
    db.save_transcript(_make_record("vid2", "Second Video"))
    items = db.list_transcripts()
    assert len(items) == 2


def test_update_summary():
    db.save_transcript(_make_record())
    db.update_summary("abc123", "New summary text")
    result = db.get_transcript("abc123")
    assert result.summary == "New summary text"


# --- FTS5 Search Tests ---

def test_search_finds_content():
    db.save_transcript(_make_record())
    results = db.search_transcripts("machine learning")
    assert len(results) >= 1
    assert results[0]["video_id"] == "abc123"


def test_search_finds_title():
    db.save_transcript(_make_record(title="Neural Networks Explained"))
    results = db.search_transcripts("neural networks")
    assert len(results) >= 1


def test_search_no_results():
    db.save_transcript(_make_record())
    results = db.search_transcripts("quantum physics")
    assert len(results) == 0


def test_search_special_characters():
    """FTS5 should not crash on special characters."""
    db.save_transcript(_make_record())
    results = db.search_transcripts("test's \"quoted\" OR AND")
    # Should not raise, result count doesn't matter
    assert isinstance(results, list)


# --- Settings Tests ---

def test_default_settings():
    settings = db.get_settings()
    assert settings.whisper_model == "small"
    assert settings.openrouter_api_key == ""
    assert settings.default_language == ""


def test_save_and_read_settings():
    settings = Settings(
        openrouter_api_key="test-key-123",
        openrouter_model="openai/gpt-4o-mini",
        whisper_model="medium",
        default_language="lt",
    )
    db.save_settings(settings)
    result = db.get_settings()
    assert result.openrouter_api_key == "test-key-123"
    assert result.whisper_model == "medium"
    assert result.default_language == "lt"


# --- Source and Summary Status Tests ---

def test_save_transcript_with_source():
    record = _make_record()
    record.source = "youtube_manual"
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result.source == "youtube_manual"


def test_save_transcript_with_summary_status():
    record = _make_record()
    record.summary_status = "done"
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result.summary_status == "done"


def test_default_source_is_whisper():
    record = _make_record()
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result.source == "whisper"


def test_update_summary_sets_status():
    record = _make_record()
    db.save_transcript(record)
    db.update_summary("abc123", "New summary", "done")
    result = db.get_transcript("abc123")
    assert result.summary == "New summary"
    assert result.summary_status == "done"


def test_update_summary_status_only():
    record = _make_record()
    db.save_transcript(record)
    db.update_summary_status("abc123", "failed")
    result = db.get_transcript("abc123")
    assert result.summary_status == "failed"


def test_summary_status_no_key():
    record = _make_record()
    record.summary_status = "no_key"
    db.save_transcript(record)
    result = db.get_transcript("abc123")
    assert result.summary_status == "no_key"


def test_migration_on_existing_db(tmp_path):
    """Simulate an old DB without source/summary_status columns."""
    old_db = tmp_path / "old.db"
    import sqlite3
    conn = sqlite3.connect(str(old_db))
    conn.executescript("""
        CREATE TABLE transcripts (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            language TEXT NOT NULL,
            duration REAL NOT NULL,
            segments_json TEXT NOT NULL,
            summary TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO transcripts (video_id, title, url, language, duration, segments_json)
        VALUES ('old1', 'Old Video', 'https://yt.com/old1', 'en', 60.0, '[]');
    """)
    conn.commit()
    conn.close()

    with patch.object(db, "DB_PATH", old_db):
        db.init_db()
        result = db.get_transcript("old1")
        assert result is not None
        assert result.source == "whisper"  # Default for old rows
        assert result.summary_status == ""  # Default empty


def test_re_transcribe_overwrites_source():
    """Re-transcribing should overwrite source from youtube to whisper."""
    record = _make_record()
    record.source = "youtube_auto"
    db.save_transcript(record)

    record.source = "whisper"
    record.summary = "Updated by Whisper"
    db.save_transcript(record)

    result = db.get_transcript("abc123")
    assert result.source == "whisper"
    assert result.summary == "Updated by Whisper"

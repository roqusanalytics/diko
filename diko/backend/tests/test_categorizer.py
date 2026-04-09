"""Tests for categorizer.py: taxonomy, LLM response parsing, and database integration."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import database as db
from categorizer import (
    CATEGORIES,
    CATEGORY_LABELS_LT,
    parse_categories_from_response,
)
from models import TranscriptRecord, TranscriptSegment


@pytest.fixture(autouse=True)
def mock_keychain():
    import keychain
    _store = {}
    with patch.object(keychain, "get_secret", side_effect=lambda k: _store.get(k)), \
         patch.object(keychain, "set_secret", side_effect=lambda k, v: _store.update({k: v}) or True), \
         patch.object(keychain, "migrate_from_db", return_value=False):
        yield


@pytest.fixture(autouse=True)
def temp_db(tmp_path):
    test_db = tmp_path / "test.db"
    with patch.object(db, "DB_PATH", test_db):
        db.init_db()
        yield


def _make_record(video_id="cat1", **kwargs) -> TranscriptRecord:
    defaults = dict(
        video_id=video_id,
        title="Test Video",
        url=f"https://youtube.com/watch?v={video_id}",
        language="en",
        duration=120.0,
        segments=[TranscriptSegment(0.0, 3.0, "Hello")],
        summary="A test summary.",
    )
    defaults.update(kwargs)
    return TranscriptRecord(**defaults)


# --- Taxonomy ---

def test_taxonomy_has_other():
    assert "Other" in CATEGORIES


def test_all_categories_have_lt_labels():
    for cat in CATEGORIES:
        assert cat in CATEGORY_LABELS_LT, f"Missing LT label for {cat}"


# --- parse_categories_from_response ---

def test_parse_happy_path():
    response = '**Santrauka** — test summary.\n\nCATEGORIES: ["AI", "Programming"]'
    summary, cats = parse_categories_from_response(response)
    assert summary == "**Santrauka** — test summary."
    assert cats == ["AI", "Programming"]


def test_parse_single_category():
    response = 'Summary text.\nCATEGORIES: ["Business"]'
    summary, cats = parse_categories_from_response(response)
    assert "Summary text" in summary
    assert cats == ["Business"]


def test_parse_invalid_category_filtered():
    response = 'Summary.\nCATEGORIES: ["AI", "NotARealCategory", "Science"]'
    summary, cats = parse_categories_from_response(response)
    assert cats == ["AI", "Science"]
    assert "NotARealCategory" not in cats


def test_parse_all_invalid_falls_back_to_other():
    response = 'Summary.\nCATEGORIES: ["FakeCategory"]'
    summary, cats = parse_categories_from_response(response)
    assert cats == ["Other"]


def test_parse_malformed_json_falls_back_to_other():
    response = 'Summary.\nCATEGORIES: not json at all'
    summary, cats = parse_categories_from_response(response)
    assert cats == ["Other"]
    assert "Summary." in summary


def test_parse_no_categories_marker():
    response = "Just a normal summary without categories."
    summary, cats = parse_categories_from_response(response)
    assert summary == response
    assert cats == ["Other"]


def test_parse_empty_array():
    response = 'Summary.\nCATEGORIES: []'
    summary, cats = parse_categories_from_response(response)
    assert cats == ["Other"]


def test_parse_preserves_summary_formatting():
    response = (
        "**Santrauka** — Some text.\n\n"
        "**Esminiai punktai:**\n- Point 1\n- Point 2\n\n"
        'CATEGORIES: ["AI"]'
    )
    summary, cats = parse_categories_from_response(response)
    assert "**Santrauka**" in summary
    assert "**Esminiai punktai:**" in summary
    assert "CATEGORIES" not in summary
    assert cats == ["AI"]


# --- Database integration ---

def test_save_and_read_categories():
    record = _make_record(categories=["AI", "Programming"], category_status="done")
    db.save_transcript(record)
    loaded = db.get_transcript("cat1")
    assert loaded.categories == ["AI", "Programming"]
    assert loaded.category_status == "done"


def test_update_categories():
    record = _make_record()
    db.save_transcript(record)
    db.update_categories("cat1", ["Science", "Education"], "done")
    loaded = db.get_transcript("cat1")
    assert loaded.categories == ["Science", "Education"]
    assert loaded.category_status == "done"


def test_update_category_status():
    record = _make_record()
    db.save_transcript(record)
    db.update_category_status("cat1", "pending")
    loaded = db.get_transcript("cat1")
    assert loaded.category_status == "pending"


def test_get_category_counts():
    r1 = _make_record("v1", categories=["AI", "Programming"], category_status="done")
    r2 = _make_record("v2", categories=["AI", "Business"], category_status="done")
    r3 = _make_record("v3", categories=["Science"], category_status="done")
    db.save_transcript(r1)
    db.save_transcript(r2)
    db.save_transcript(r3)

    counts = db.get_category_counts()
    count_map = {c["name"]: c["count"] for c in counts}
    assert count_map["AI"] == 2
    assert count_map["Programming"] == 1
    assert count_map["Business"] == 1
    assert count_map["Science"] == 1


def test_get_category_counts_ignores_non_done():
    r1 = _make_record("v1", categories=["AI"], category_status="done")
    r2 = _make_record("v2", categories=["AI"], category_status="failed")
    db.save_transcript(r1)
    db.save_transcript(r2)

    counts = db.get_category_counts()
    count_map = {c["name"]: c["count"] for c in counts}
    assert count_map.get("AI") == 1


def test_list_transcripts_includes_categories():
    r = _make_record(categories=["AI", "Design"], category_status="done")
    db.save_transcript(r)
    items = db.list_transcripts()
    assert len(items) == 1
    assert items[0]["categories"] == ["AI", "Design"]
    assert items[0]["category_status"] == "done"


def test_categories_idempotent():
    """Re-categorizing same transcript replaces categories."""
    record = _make_record(categories=["AI"], category_status="done")
    db.save_transcript(record)
    db.update_categories("cat1", ["Business", "Finance"], "done")
    loaded = db.get_transcript("cat1")
    assert loaded.categories == ["Business", "Finance"]

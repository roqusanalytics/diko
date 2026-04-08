"""Tests for YouTube caption extraction and VTT parsing."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from downloader import _parse_vtt, get_captions
from models import TranscriptSegment


# --- VTT Parsing Tests ---


def test_parse_vtt_basic(tmp_path):
    """Parse a standard VTT file with timestamps and text."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:04.000\n"
        "Hello world\n\n"
        "00:00:04.000 --> 00:00:08.500\n"
        "This is a test\n"
    )
    segments = _parse_vtt(vtt)
    assert len(segments) == 2
    assert segments[0].start == 1.0
    assert segments[0].end == 4.0
    assert segments[0].text == "Hello world"
    assert segments[1].start == 4.0
    assert segments[1].end == 8.5
    assert segments[1].text == "This is a test"


def test_parse_vtt_strips_formatting_tags(tmp_path):
    """VTT formatting tags like <c> and inline timestamps should be stripped."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:04.000\n"
        "<c>Hello</c> <00:00:02.500>world\n"
    )
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "Hello world"


def test_parse_vtt_deduplicates_repeated_lines(tmp_path):
    """YouTube auto-captions often repeat lines. Should deduplicate."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:03.000\n"
        "Hello world\n\n"
        "00:00:02.000 --> 00:00:05.000\n"
        "Hello world\n\n"
        "00:00:04.000 --> 00:00:07.000\n"
        "Different text\n"
    )
    segments = _parse_vtt(vtt)
    assert len(segments) == 2
    assert segments[0].text == "Hello world"
    assert segments[1].text == "Different text"


def test_parse_vtt_empty_file(tmp_path):
    """Empty VTT file should return empty list."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text("WEBVTT\n\n")
    segments = _parse_vtt(vtt)
    assert segments == []


def test_parse_vtt_no_timestamps(tmp_path):
    """VTT with no valid timestamps should return empty list."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text("WEBVTT\n\nJust some random text\n")
    segments = _parse_vtt(vtt)
    assert segments == []


def test_parse_vtt_multiline_text(tmp_path):
    """VTT with multi-line caption text should join lines."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "00:00:01.000 --> 00:00:04.000\n"
        "Line one\n"
        "Line two\n\n"
        "00:00:04.000 --> 00:00:07.000\n"
        "Single line\n"
    )
    segments = _parse_vtt(vtt)
    assert len(segments) == 2
    assert segments[0].text == "Line one Line two"


def test_parse_vtt_hours(tmp_path):
    """VTT with hour timestamps should parse correctly."""
    vtt = tmp_path / "test.vtt"
    vtt.write_text(
        "WEBVTT\n\n"
        "01:30:00.000 --> 01:30:05.000\n"
        "One hour thirty\n"
    )
    segments = _parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].start == 5400.0
    assert segments[0].end == 5405.0


# --- get_captions Integration Tests ---


def test_get_captions_returns_none_on_error():
    """get_captions should return None when yt-dlp fails."""
    with patch("downloader.yt_dlp.YoutubeDL") as mock_ydl:
        mock_ydl.return_value.__enter__ = MagicMock(
            side_effect=Exception("Network error")
        )
        mock_ydl.return_value.__exit__ = MagicMock(return_value=False)
        result = get_captions("https://youtube.com/watch?v=invalid", "en")
        assert result is None


def test_get_captions_returns_none_when_no_subtitles():
    """get_captions should return None when video has no subtitles."""
    mock_info = {
        "id": "test123",
        "title": "Test Video",
        "duration": 120,
        "subtitles": {},
        "automatic_captions": {},
    }
    with patch("downloader.yt_dlp.YoutubeDL") as mock_ydl:
        instance = MagicMock()
        instance.extract_info.return_value = mock_info
        mock_ydl.return_value.__enter__ = MagicMock(return_value=instance)
        mock_ydl.return_value.__exit__ = MagicMock(return_value=False)
        result = get_captions("https://youtube.com/watch?v=test123", "en")
        assert result is None

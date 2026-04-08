"""Tests for exporter.py: SRT and PDF HTML generation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from exporter import to_srt, to_pdf_html
from models import TranscriptSegment


def _segments():
    return [
        TranscriptSegment(start=0.0, end=3.5, text="Hello world"),
        TranscriptSegment(start=3.5, end=7.2, text="This is a test"),
    ]


def test_srt_format():
    srt = to_srt(_segments())
    assert "1\n00:00:00,000 --> 00:00:03,500\nHello world" in srt
    assert "2\n00:00:03,500 --> 00:00:07,200\nThis is a test" in srt


def test_srt_numbering():
    srt = to_srt(_segments())
    lines = srt.strip().split("\n\n")
    assert lines[0].startswith("1\n")
    assert lines[1].startswith("2\n")


def test_pdf_html_contains_content():
    html = to_pdf_html("Test Title", _segments(), "A test summary")
    assert "Test Title" in html
    assert "Hello world" in html
    assert "A test summary" in html
    assert "AI Santrauka" in html


def test_pdf_html_without_summary():
    html = to_pdf_html("Test Title", _segments())
    assert "Test Title" in html
    assert "AI Santrauka" not in html

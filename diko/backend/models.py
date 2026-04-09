"""Typed dataclasses for inter-service communication."""

from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    PARTIAL = "partial"
    ERROR = "error"


@dataclass
class DownloadResult:
    audio_path: str
    video_id: str
    title: str
    duration: float  # seconds
    thumbnail_url: str = ""
    channel_name: str = ""
    view_count: int = 0
    like_count: int = 0


@dataclass
class TranscriptSegment:
    start: float  # seconds
    end: float
    text: str


@dataclass
class TranscriptionResult:
    segments: list[TranscriptSegment]
    language: str
    duration: float  # total duration in seconds


@dataclass
class SummaryResult:
    text: str
    model: str  # which model was used
    categories: list[str] = field(default_factory=list)


@dataclass
class TranscriptRecord:
    video_id: str
    title: str
    url: str
    language: str
    duration: float
    segments: list[TranscriptSegment]
    summary: str = ""
    summary_status: str = ""  # pending, done, failed, no_key
    source: str = "whisper"  # whisper, youtube_manual, youtube_auto
    translated_text: str = ""  # LLM-translated full text
    channel_name: str = ""
    view_count: int = 0
    like_count: int = 0
    categories: list[str] = field(default_factory=list)  # auto-assigned categories
    category_status: str = ""  # pending, done, failed, no_key
    created_at: str = ""


@dataclass
class MediaDownloadResult:
    file_path: str
    video_id: str
    title: str
    duration: float
    format: str  # mp3, m4a, wav, flac, ogg, mp4, webm
    file_size: int = 0  # bytes


@dataclass
class Settings:
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4"
    whisper_model: str = "small"
    default_language: str = ""  # empty = auto-detect
    media_format: str = "mp3"  # last-used format default
    media_quality: str = "320"  # last-used quality default

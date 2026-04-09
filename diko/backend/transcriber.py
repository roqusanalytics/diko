"""Whisper transcription using faster-whisper. Singleton model with threading lock."""

import threading
from typing import Callable

from faster_whisper import WhisperModel

from models import TranscriptionResult, TranscriptSegment

# Singleton: load model once, protect with lock
_model: WhisperModel | None = None
_model_lock = threading.Lock()
_model_name: str = ""


def _get_model(model_size: str = "small") -> WhisperModel:
    """Get or create the singleton Whisper model."""
    global _model, _model_name
    with _model_lock:
        if _model is None or _model_name != model_size:
            _model = WhisperModel(model_size, device="cpu", compute_type="int8")
            _model_name = model_size
        return _model


def transcribe(
    audio_path: str,
    language: str | None = None,
    model_size: str = "small",
    on_progress: Callable[[float], None] | None = None,
) -> TranscriptionResult:
    """
    Transcribe audio file using faster-whisper.

    Runs under the singleton lock to prevent concurrent Whisper calls
    which would OOM on a 16GB Mac.

    Args:
        audio_path: Path to audio file (m4a, wav, etc.)
        language: ISO language code or None for auto-detect
        model_size: Whisper model size (tiny/base/small/medium/large)
        on_progress: Optional callback with progress percentage (0.0-1.0)
    """
    model = _get_model(model_size)

    with _model_lock:
        segments_iter, info = model.transcribe(
            audio_path,
            language=language if language else None,
            beam_size=5,
            vad_filter=True,
        )

        total_duration = info.duration
        detected_language = info.language
        segments: list[TranscriptSegment] = []

        for segment in segments_iter:
            segments.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text.strip(),
                )
            )

            if on_progress and total_duration > 0:
                progress = min(segment.end / total_duration, 1.0)
                on_progress(progress)

    return TranscriptionResult(
        segments=segments,
        language=detected_language,
        duration=total_duration,
    )

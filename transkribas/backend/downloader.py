"""YouTube audio/media downloader using yt-dlp."""

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import yt_dlp

from models import DownloadResult, MediaDownloadResult, TranscriptSegment

logger = logging.getLogger(__name__)


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID from URL without calling YouTube API.

    Parses the ID from the URL directly to avoid bot detection on
    cloud servers. Falls back to yt-dlp only if regex fails.
    """
    # Try regex first (no network call, no bot detection)
    vid = _parse_video_id(url)
    if vid:
        return vid

    # Fallback to yt-dlp (works on localhost, may fail on cloud)
    with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        return info["id"]


def _parse_video_id(url: str) -> str | None:
    """Parse YouTube video ID from URL using regex. No network call."""
    patterns = [
        r"(?:youtube\.com/watch\?.*v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_playlist_urls(url: str) -> list[dict]:
    """Extract all video URLs from a YouTube playlist. Returns list of {url, title, video_id, duration}."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "force_generic_extractor": False,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("_type") == "playlist" and "entries" in info:
                return [
                    {
                        "url": f"https://www.youtube.com/watch?v={e['id']}",
                        "title": e.get("title", "Unknown"),
                        "video_id": e["id"],
                        "duration": e.get("duration", 0) or 0,
                    }
                    for e in info["entries"]
                    if e and e.get("id")
                ]
    except Exception as e:
        logger.warning(f"Playlist extraction failed: {e}")
    return []


def is_playlist_url(url: str) -> bool:
    """Check if a URL points to a YouTube playlist."""
    return "list=" in url and ("youtube.com" in url or "youtu.be" in url)


def get_captions(
    url: str, language: str = "en"
) -> dict | None:
    """
    Try to get YouTube captions for a video. Returns None if no captions available.

    Returns dict with keys: segments, source, video_id, title, duration, channel_name, view_count, like_count.
    source is 'youtube_manual' or 'youtube_auto'.
    """
    try:
        tmp_dir = Path(tempfile.mkdtemp(prefix="transkribas_sub_"))
        langs = [language, "en"] if language and language != "en" else ["en"]

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": langs,
            "subtitlesformat": "vtt",
            "skip_download": True,
            "outtmpl": str(tmp_dir / "%(id)s"),
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        video_id = info["id"]
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        channel_name = info.get("uploader") or info.get("channel") or ""
        view_count = info.get("view_count") or 0
        like_count = info.get("like_count") or 0

        meta = {
            "video_id": video_id, "title": title, "duration": duration,
            "channel_name": channel_name, "view_count": view_count, "like_count": like_count,
        }

        # Check for downloaded subtitle files. Prefer manual over auto-generated.
        # yt-dlp saves as: {id}.{lang}.vtt (manual) or {id}.{lang}.vtt (auto)
        # Manual subs are in info['subtitles'], auto in info['automatic_captions']
        manual_subs = info.get("subtitles", {})
        auto_subs = info.get("automatic_captions", {})

        for lang_code in langs:
            # Try manual captions first
            if lang_code in manual_subs:
                vtt_path = _find_vtt_file(tmp_dir, video_id, lang_code)
                if vtt_path:
                    segments = _parse_vtt(vtt_path)
                    if segments:
                        _cleanup_dir(tmp_dir)
                        return {**meta, "segments": segments, "source": "youtube_manual"}

            # Then auto-generated
            if lang_code in auto_subs:
                vtt_path = _find_vtt_file(tmp_dir, video_id, lang_code)
                if vtt_path:
                    segments = _parse_vtt(vtt_path)
                    if segments:
                        _cleanup_dir(tmp_dir)
                        return {**meta, "segments": segments, "source": "youtube_auto"}

        _cleanup_dir(tmp_dir)
        return None

    except Exception as e:
        logger.warning(f"Caption extraction failed, falling back to Whisper: {e}")
        return None


def _find_vtt_file(tmp_dir: Path, video_id: str, lang_code: str) -> Path | None:
    """Find a VTT subtitle file in the temp directory."""
    for f in tmp_dir.iterdir():
        if f.suffix == ".vtt" and lang_code in f.stem:
            return f
    return None


def _parse_vtt(vtt_path: Path) -> list[TranscriptSegment]:
    """Parse a VTT subtitle file into TranscriptSegment list."""
    content = vtt_path.read_text(encoding="utf-8")
    segments: list[TranscriptSegment] = []

    # VTT timestamp pattern: HH:MM:SS.mmm --> HH:MM:SS.mmm
    timestamp_pattern = re.compile(
        r"(\d{2}):(\d{2}):(\d{2})\.(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})\.(\d{3})"
    )

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        match = timestamp_pattern.match(lines[i].strip())
        if match:
            start = (
                int(match.group(1)) * 3600
                + int(match.group(2)) * 60
                + int(match.group(3))
                + int(match.group(4)) / 1000
            )
            end = (
                int(match.group(5)) * 3600
                + int(match.group(6)) * 60
                + int(match.group(7))
                + int(match.group(8)) / 1000
            )

            # Collect text lines until next timestamp or blank line
            i += 1
            text_parts = []
            while i < len(lines) and lines[i].strip() and not timestamp_pattern.match(lines[i].strip()):
                line = lines[i].strip()
                # Strip VTT formatting tags like <c> </c> <00:00:01.234>
                line = re.sub(r"<[^>]+>", "", line)
                if line:
                    text_parts.append(line)
                i += 1

            text = " ".join(text_parts).strip()
            if text and (not segments or segments[-1].text != text):
                segments.append(TranscriptSegment(start=start, end=end, text=text))
        else:
            i += 1

    return segments


def _cleanup_dir(dir_path: Path) -> None:
    """Remove a temporary directory and its contents."""
    try:
        for f in dir_path.iterdir():
            f.unlink(missing_ok=True)
        dir_path.rmdir()
    except OSError:
        pass


def download_audio(url: str) -> DownloadResult:
    """Download audio from YouTube URL as m4a. Returns DownloadResult with file path."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="transkribas_"))

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

        video_id = info["id"]
        title = info.get("title", "Unknown")
        duration = info.get("duration", 0)
        thumbnail = info.get("thumbnail", "")
        channel_name = info.get("uploader") or info.get("channel") or ""
        view_count = info.get("view_count") or 0
        like_count = info.get("like_count") or 0

        # Find the downloaded file
        ext = info.get("ext", "m4a")
        audio_path = str(tmp_dir / f"{video_id}.{ext}")

        if not os.path.exists(audio_path):
            # Try to find any audio file in the temp dir
            for f in tmp_dir.iterdir():
                if f.suffix in (".m4a", ".webm", ".opus", ".mp3"):
                    audio_path = str(f)
                    break

        return DownloadResult(
            audio_path=audio_path,
            video_id=video_id,
            title=title,
            duration=duration,
            thumbnail_url=thumbnail,
            channel_name=channel_name,
            view_count=view_count,
            like_count=like_count,
        )


def cleanup_audio(audio_path: str) -> None:
    """Remove temp audio file and its parent directory after transcription."""
    path = Path(audio_path)
    try:
        path.unlink(missing_ok=True)
        if path.parent.name.startswith("transkribas_"):
            path.parent.rmdir()
    except OSError:
        pass


# --- Media download (user-facing, format/quality/trim) ---

# Valid formats and quality options
AUDIO_FORMATS = {"mp3", "m4a", "wav", "flac", "ogg"}
VIDEO_FORMATS = {"mp4", "webm"}
LOSSY_FORMATS = {"mp3", "ogg"}
VALID_BITRATES = {"128", "192", "320"}
VALID_RESOLUTIONS = {"360", "720", "1080", "best"}


def _build_format_string(
    fmt: str, quality: str
) -> tuple[str, list[dict]]:
    """Build yt-dlp format string and postprocessors for the
    requested format and quality.

    Returns (format_str, postprocessors).
    """
    if fmt in AUDIO_FORMATS:
        format_str = "bestaudio[ext=m4a]/bestaudio"
        if fmt == "m4a":
            # Direct download, no conversion needed
            return format_str, []
        codec = "vorbis" if fmt == "ogg" else fmt
        pp = {
            "key": "FFmpegExtractAudio",
            "preferredcodec": codec,
        }
        if fmt in LOSSY_FORMATS and quality in VALID_BITRATES:
            pp["preferredquality"] = quality
        return format_str, [pp]

    # Video formats
    res = quality if quality in VALID_RESOLUTIONS else "best"
    if res == "best":
        height_filter = ""
    else:
        height_filter = f"[height<={res}]"

    if fmt == "mp4":
        format_str = (
            f"bestvideo{height_filter}[ext=mp4]"
            f"+bestaudio[ext=m4a]"
            f"/best{height_filter}[ext=mp4]"
            f"/best{height_filter}"
        )
    else:  # webm
        format_str = (
            f"bestvideo{height_filter}[ext=webm]"
            f"+bestaudio[ext=webm]"
            f"/best{height_filter}[ext=webm]"
            f"/best{height_filter}"
        )
    return format_str, []


def download_media(
    url: str,
    fmt: str = "mp3",
    quality: str = "320",
    start_time: float | None = None,
    end_time: float | None = None,
    on_progress: Callable[[float, str], None] | None = None,
) -> MediaDownloadResult:
    """Download media from YouTube with format conversion and
    optional trimming.

    Args:
        url: YouTube URL or video ID-based URL.
        fmt: Target format (mp3, m4a, wav, flac, ogg, mp4, webm).
        quality: Bitrate for lossy audio or resolution for video.
        start_time: Trim start in seconds (optional).
        end_time: Trim end in seconds (optional).
        on_progress: Callback(progress_0_to_1, stage) for tracking.

    Returns:
        MediaDownloadResult with file path and metadata.
    """
    if fmt not in AUDIO_FORMATS | VIDEO_FORMATS:
        raise ValueError(f"Unsupported format: {fmt}")

    tmp_dir = Path(tempfile.mkdtemp(prefix="transkribas_media_"))
    format_str, postprocessors = _build_format_string(fmt, quality)

    def progress_hook(d: dict) -> None:
        if on_progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get(
                "total_bytes_estimate", 0
            )
            downloaded = d.get("downloaded_bytes", 0)
            if total > 0:
                on_progress(downloaded / total, "downloading")

    ydl_opts: dict = {
        "format": format_str,
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [progress_hook],
    }
    if postprocessors:
        ydl_opts["postprocessors"] = postprocessors

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if on_progress:
        on_progress(1.0, "downloading")

    video_id = info["id"]
    title = info.get("title", "Unknown")
    duration = info.get("duration", 0)

    # Find the output file
    out_file = _find_output_file(tmp_dir, fmt)
    if not out_file:
        raise FileNotFoundError(
            f"Download completed but output file not found "
            f"in {tmp_dir}"
        )

    # Trim if requested
    if start_time is not None and end_time is not None:
        if on_progress:
            on_progress(0.0, "converting")
        out_file = _trim_media(out_file, start_time, end_time)
        if on_progress:
            on_progress(1.0, "converting")

    file_size = out_file.stat().st_size

    return MediaDownloadResult(
        file_path=str(out_file),
        video_id=video_id,
        title=title,
        duration=duration,
        format=fmt,
        file_size=file_size,
    )


def _find_output_file(tmp_dir: Path, fmt: str) -> Path | None:
    """Find the downloaded/converted file in the temp directory."""
    # Check for exact format match first
    for f in tmp_dir.iterdir():
        if f.suffix == f".{fmt}":
            return f
    # Fallback: any media file
    media_exts = {
        ".mp3", ".m4a", ".wav", ".flac", ".ogg",
        ".mp4", ".webm", ".mkv",
    }
    for f in tmp_dir.iterdir():
        if f.suffix in media_exts:
            return f
    return None


def _trim_media(
    file_path: Path,
    start: float,
    end: float,
) -> Path:
    """Trim a media file using ffmpeg. Returns path to trimmed file."""
    trimmed = file_path.with_stem(file_path.stem + "_trimmed")
    cmd = [
        "ffmpeg", "-y",
        "-i", str(file_path),
        "-ss", str(start),
        "-to", str(end),
        "-c", "copy",
        str(trimmed),
    ]
    result = subprocess.run(
        cmd, capture_output=True, timeout=300
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg trim failed: {result.stderr.decode()[:200]}"
        )
    # Remove the original, keep the trimmed
    file_path.unlink(missing_ok=True)
    return trimmed


def cleanup_media_dir(dir_path: str) -> None:
    """Remove a media temp directory and all its contents."""
    path = Path(dir_path)
    if not path.name.startswith("transkribas_media_"):
        return
    try:
        for f in path.iterdir():
            f.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass

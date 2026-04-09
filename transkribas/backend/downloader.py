"""YouTube audio/media downloader using yt-dlp."""

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

import httpx
import yt_dlp

from models import DownloadResult, MediaDownloadResult, TranscriptSegment

logger = logging.getLogger(__name__)

# Valid formats and quality options
AUDIO_FORMATS = {"mp3", "m4a", "wav", "flac", "ogg"}
VIDEO_FORMATS = {"mp4", "webm"}
LOSSY_FORMATS = {"mp3", "ogg"}
VALID_BITRATES = {"128", "192", "320"}
VALID_RESOLUTIONS = {"360", "720", "1080", "best"}


def _yt_cookie_opts() -> dict:
    """Return yt-dlp cookie + JS challenge options for cloud deployment."""
    opts: dict = {}
    cookies_path = os.environ.get("YT_COOKIES_PATH", "")
    if cookies_path and Path(cookies_path).is_file():
        opts["cookiefile"] = cookies_path
        # Enable remote JS challenge solver (needed on cloud servers)
        opts["remote_components"] = ["ejs:github"]
    return opts


def _worker_base_url() -> str:
    return os.environ.get("YTDLP_WORKER_URL", "").rstrip("/")


def _worker_token() -> str:
    return os.environ.get("YTDLP_WORKER_TOKEN", "")


def _use_worker() -> bool:
    return bool(_worker_base_url())


def _transcript_worker_url() -> str:
    """Residential transcript worker URL (Flask on Tailscale Funnel)."""
    return os.environ.get("TRANSCRIPT_WORKER_URL", "").rstrip("/")


def _transcript_worker_token() -> str:
    return os.environ.get("TRANSCRIPT_WORKER_TOKEN", "")


def fetch_transcript_from_worker(
    video_id: str, language: str = "en"
) -> list[TranscriptSegment] | None:
    """Fetch transcript text from the residential worker.

    The worker runs youtube-transcript-api from a residential IP,
    bypassing YouTube's datacenter bot detection.
    Returns list of TranscriptSegment or None if unavailable.
    """
    base = _transcript_worker_url()
    if not base:
        return None

    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = _transcript_worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=30) as client:
            r = client.post(
                f"{base}/transcript",
                json={"video_id": video_id, "language": language},
                headers=headers,
            )
            r.raise_for_status()
            data = r.json()

        if not data.get("ok"):
            logger.warning(f"Transcript worker error: {data.get('error', 'unknown')}")
            return None

        segments = []
        for s in data.get("segments", []):
            segments.append(TranscriptSegment(
                start=float(s["start"]),
                end=float(s["start"]) + float(s.get("duration", 0)),
                text=s.get("text", ""),
            ))

        if not segments:
            return None

        logger.info(f"Residential worker returned {len(segments)} segments for {video_id}")
        return segments

    except Exception as e:
        logger.warning(f"Transcript worker unreachable: {e}")
        return None


def _worker_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = _worker_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _decode_meta_header(meta_b64: str | None) -> dict:
    if not meta_b64:
        return {}
    return json.loads(base64.urlsafe_b64decode(meta_b64.encode()).decode("utf-8"))


def _worker_json(path: str, payload: dict, timeout: float = 120.0) -> dict:
    """POST JSON to the residential worker and return decoded JSON."""
    url = f"{_worker_base_url()}{path}"
    with httpx.Client(timeout=timeout) as client:
        res = client.post(url, json=payload, headers=_worker_headers())
        res.raise_for_status()
        return res.json()


def _worker_download(
    path: str,
    payload: dict,
    tmp_prefix: str,
    fallback_ext: str,
    timeout: float = 900.0,
) -> tuple[Path, dict]:
    """Stream a downloaded file from the worker into a local temp file."""
    url = f"{_worker_base_url()}{path}"
    tmp_dir = Path(tempfile.mkdtemp(prefix=tmp_prefix))
    meta: dict = {}
    ext = fallback_ext

    with httpx.Client(timeout=timeout) as client:
        with client.stream("POST", url, json=payload, headers=_worker_headers()) as res:
            res.raise_for_status()
            meta = _decode_meta_header(res.headers.get("X-Transkribas-Meta"))
            ext = meta.get("ext", fallback_ext) or fallback_ext
            video_id = meta.get("video_id", "remote")
            out_path = tmp_dir / f"{video_id}.{ext}"
            with out_path.open("wb") as f:
                for chunk in res.iter_bytes():
                    f.write(chunk)

    meta.setdefault("file_size", out_path.stat().st_size)
    meta.setdefault("ext", ext)
    return out_path, meta


def extract_video_id(url: str) -> str:
    """Extract YouTube video ID, optionally via residential worker."""
    if _use_worker():
        return _worker_json("/internal/youtube/extract-video-id", {"url": url})["video_id"]
    return extract_video_id_local(url)


def extract_video_id_local(url: str) -> str:
    """Extract YouTube video ID from URL without calling YouTube API.

    Parses the ID from the URL directly to avoid bot detection on
    cloud servers. Falls back to yt-dlp only if regex fails.
    """
    # Try regex first (no network call, no bot detection)
    vid = _parse_video_id(url)
    if vid:
        return vid

    # Fallback to yt-dlp (works on localhost, may fail on cloud)
    with yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, **_yt_cookie_opts()}) as ydl:
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
    """Extract playlist entries, optionally via residential worker."""
    if _use_worker():
        return _worker_json("/internal/youtube/playlist", {"url": url}).get("videos", [])
    return extract_playlist_urls_local(url)


def extract_playlist_urls_local(url: str) -> list[dict]:
    """Extract all video URLs from a YouTube playlist. Returns list of {url, title, video_id, duration}."""
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "force_generic_extractor": False,
        **_yt_cookie_opts(),
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
    """Try to get captions, optionally via residential worker."""
    if _use_worker():
        data = _worker_json(
            "/internal/youtube/captions",
            {"url": url, "language": language},
            timeout=300.0,
        )
        if not data.get("ok"):
            return None
        return {
            "video_id": data["video_id"],
            "title": data["title"],
            "duration": data["duration"],
            "channel_name": data.get("channel_name", ""),
            "view_count": data.get("view_count", 0),
            "like_count": data.get("like_count", 0),
            "source": data["source"],
            "segments": [TranscriptSegment(**s) for s in data["segments"]],
        }
    return get_captions_local(url, language)


def get_captions_local(
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
            **_yt_cookie_opts(),
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
    """Download audio locally or through the residential worker."""
    if _use_worker():
        audio_path, meta = _worker_download(
            "/internal/youtube/audio",
            {"url": url},
            tmp_prefix="transkribas_",
            fallback_ext="m4a",
        )
        return DownloadResult(
            audio_path=str(audio_path),
            video_id=meta.get("video_id", audio_path.stem),
            title=meta.get("title", "Unknown"),
            duration=float(meta.get("duration", 0)),
            thumbnail_url=meta.get("thumbnail_url", ""),
            channel_name=meta.get("channel_name", ""),
            view_count=int(meta.get("view_count", 0)),
            like_count=int(meta.get("like_count", 0)),
        )
    return download_audio_local(url)


def download_audio_local(url: str) -> DownloadResult:
    """Download audio from YouTube URL as m4a. Returns DownloadResult with file path."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="transkribas_"))

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": str(tmp_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        **_yt_cookie_opts(),
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
    """Download media locally or through the residential worker."""
    if _use_worker():
        if on_progress:
            on_progress(0.05, "delegating")
        file_path, meta = _worker_download(
            "/internal/youtube/media",
            {
                "url": url,
                "format": fmt,
                "quality": quality,
                "start_time": start_time,
                "end_time": end_time,
            },
            tmp_prefix="transkribas_media_",
            fallback_ext=fmt,
            timeout=1800.0,
        )
        if on_progress:
            on_progress(1.0, "downloading")
        return MediaDownloadResult(
            file_path=str(file_path),
            video_id=meta.get("video_id", file_path.stem),
            title=meta.get("title", "Unknown"),
            duration=float(meta.get("duration", 0)),
            format=meta.get("format", fmt),
            file_size=int(meta.get("file_size", file_path.stat().st_size)),
        )
    return download_media_local(
        url,
        fmt=fmt,
        quality=quality,
        start_time=start_time,
        end_time=end_time,
        on_progress=on_progress,
    )


def download_media_local(
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
        **_yt_cookie_opts(),
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

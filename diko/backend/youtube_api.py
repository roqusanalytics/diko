"""YouTube Data API v3 fallback for video metadata and caption availability.

Used when yt-dlp fails (bot detection on cloud servers).
Requires YOUTUBE_API_KEY env var.
"""

import logging
import os
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
BASE_URL = "https://www.googleapis.com/youtube/v3"


@dataclass
class VideoMetadata:
    video_id: str
    title: str
    channel_name: str
    duration: int  # seconds
    view_count: int
    like_count: int
    has_captions: bool
    caption_languages: list[str]


def _parse_duration(iso: str) -> int:
    """Parse ISO 8601 duration (PT46M11S) to seconds."""
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso)
    if not match:
        return 0
    h = int(match.group(1) or 0)
    m = int(match.group(2) or 0)
    s = int(match.group(3) or 0)
    return h * 3600 + m * 60 + s


def get_video_metadata(video_id: str) -> VideoMetadata | None:
    """Fetch video metadata via YouTube Data API v3.

    Works from any IP (no bot detection). Requires API key.
    """
    if not API_KEY:
        return None

    try:
        with httpx.Client(timeout=10) as client:
            # Get video details
            r = client.get(
                f"{BASE_URL}/videos",
                params={
                    "part": "snippet,contentDetails,statistics",
                    "id": video_id,
                    "key": API_KEY,
                },
            )
            r.raise_for_status()
            data = r.json()

            if not data.get("items"):
                return None

            item = data["items"][0]
            snippet = item["snippet"]
            stats = item.get("statistics", {})
            content = item["contentDetails"]

            # Get caption list
            cr = client.get(
                f"{BASE_URL}/captions",
                params={
                    "part": "snippet",
                    "videoId": video_id,
                    "key": API_KEY,
                },
            )
            captions = []
            if cr.status_code == 200:
                cap_data = cr.json()
                captions = [
                    c["snippet"]["language"]
                    for c in cap_data.get("items", [])
                ]

            return VideoMetadata(
                video_id=video_id,
                title=snippet.get("title", "Unknown"),
                channel_name=snippet.get("channelTitle", ""),
                duration=_parse_duration(
                    content.get("duration", "PT0S")
                ),
                view_count=int(stats.get("viewCount", 0)),
                like_count=int(stats.get("likeCount", 0)),
                has_captions=bool(captions),
                caption_languages=captions,
            )

    except Exception as e:
        logger.warning(f"YouTube API failed: {e}")
        return None

"""SQLite database with FTS5 for transcript storage, search, and settings."""

import json
import logging
import os
import sqlite3
from pathlib import Path

import keychain
from models import Settings, TranscriptRecord, TranscriptSegment

logger = logging.getLogger(__name__)

DB_PATH = Path(os.environ.get(
    "DB_PATH",
    Path.home() / "Documents" / "5. AI projektai" / "YT_transcribe" / "yt_transcribe",
))


def _get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist, then run migrations."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transcripts (
            video_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            language TEXT NOT NULL,
            duration REAL NOT NULL,
            segments_json TEXT NOT NULL,
            summary TEXT DEFAULT '',
            summary_status TEXT DEFAULT '',
            source TEXT DEFAULT 'whisper',
            translated_text TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS transcripts_fts USING fts5(
            video_id,
            title,
            content,
            content_rowid='rowid'
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS saved_models (
            model_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            is_favorite INTEGER DEFAULT 0,
            added_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS collections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS transcript_collections (
            video_id TEXT NOT NULL,
            collection_id INTEGER NOT NULL,
            PRIMARY KEY (video_id, collection_id),
            FOREIGN KEY (video_id) REFERENCES transcripts(video_id) ON DELETE CASCADE,
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE
        );
    """)

    # Migrate existing DBs: add new columns if missing
    _migrate_columns(conn)
    conn.close()


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """Add columns that may be missing from older databases."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(transcripts)").fetchall()}
    if "source" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN source TEXT DEFAULT 'whisper'")
    if "summary_status" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN summary_status TEXT DEFAULT ''")
    if "translated_text" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN translated_text TEXT DEFAULT ''")
    if "channel_name" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN channel_name TEXT DEFAULT ''")
    if "view_count" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN view_count INTEGER DEFAULT 0")
    if "like_count" not in existing:
        conn.execute("ALTER TABLE transcripts ADD COLUMN like_count INTEGER DEFAULT 0")
    conn.commit()


def save_transcript(record: TranscriptRecord) -> None:
    """Insert or update a transcript record."""
    conn = _get_conn()
    segments_json = json.dumps(
        [{"start": s.start, "end": s.end, "text": s.text} for s in record.segments]
    )
    full_text = " ".join(s.text for s in record.segments)

    conn.execute(
        """INSERT OR REPLACE INTO transcripts
           (video_id, title, url, language, duration, segments_json, summary, summary_status, source, translated_text, channel_name, view_count, like_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (record.video_id, record.title, record.url, record.language,
         record.duration, segments_json, record.summary, record.summary_status, record.source,
         record.translated_text, record.channel_name, record.view_count, record.like_count),
    )

    # Update FTS index
    conn.execute("DELETE FROM transcripts_fts WHERE video_id = ?", (record.video_id,))
    conn.execute(
        "INSERT INTO transcripts_fts (video_id, title, content) VALUES (?, ?, ?)",
        (record.video_id, record.title, full_text),
    )
    conn.commit()
    conn.close()


def get_transcript(video_id: str) -> TranscriptRecord | None:
    """Get a transcript by video ID."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM transcripts WHERE video_id = ?", (video_id,)
    ).fetchone()
    conn.close()

    if not row:
        return None

    segments = [
        TranscriptSegment(**s) for s in json.loads(row["segments_json"])
    ]

    return TranscriptRecord(
        video_id=row["video_id"],
        title=row["title"],
        url=row["url"],
        language=row["language"],
        duration=row["duration"],
        segments=segments,
        summary=row["summary"],
        summary_status=row["summary_status"] if "summary_status" in row.keys() else "",
        source=row["source"] if "source" in row.keys() else "whisper",
        translated_text=row["translated_text"] if "translated_text" in row.keys() else "",
        channel_name=row["channel_name"] if "channel_name" in row.keys() else "",
        view_count=row["view_count"] if "view_count" in row.keys() else 0,
        like_count=row["like_count"] if "like_count" in row.keys() else 0,
        created_at=row["created_at"],
    )


def _sanitize_fts_query(query: str) -> str:
    """Sanitize a query string for FTS5. Remove special characters that cause syntax errors."""
    # FTS5 special chars: AND OR NOT NEAR " * ^
    # Wrap each word in double quotes to treat as literal
    words = query.split()
    sanitized = " ".join(f'"{w}"' for w in words if w.strip())
    return sanitized


def search_transcripts(query: str) -> list[dict]:
    """Full-text search across all transcripts. Returns matching excerpts."""
    safe_query = _sanitize_fts_query(query)
    if not safe_query:
        return []
    conn = _get_conn()
    rows = conn.execute(
        """SELECT f.video_id, f.title,
                  snippet(transcripts_fts, 2, '<mark>', '</mark>', '...', 40) as excerpt,
                  t.language, t.duration, t.created_at
           FROM transcripts_fts f
           JOIN transcripts t ON f.video_id = t.video_id
           WHERE transcripts_fts MATCH ?
           ORDER BY rank
           LIMIT 50""",
        (safe_query,),
    ).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def list_transcripts() -> list[dict]:
    """List all transcripts ordered by creation date."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT video_id, title, url, language, duration, summary, source, summary_status, channel_name, view_count, like_count, created_at
           FROM transcripts ORDER BY created_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def delete_transcript(video_id: str) -> None:
    """Delete a transcript and its FTS index entry."""
    conn = _get_conn()
    conn.execute("DELETE FROM transcripts WHERE video_id = ?", (video_id,))
    conn.execute("DELETE FROM transcripts_fts WHERE video_id = ?", (video_id,))
    conn.commit()
    conn.close()


def update_summary(video_id: str, summary: str, status: str = "done") -> None:
    """Update the summary and its status for an existing transcript."""
    conn = _get_conn()
    conn.execute(
        "UPDATE transcripts SET summary = ?, summary_status = ? WHERE video_id = ?",
        (summary, status, video_id),
    )
    conn.commit()
    conn.close()


def update_summary_status(video_id: str, status: str) -> None:
    """Update only the summary status (pending, done, failed, no_key)."""
    conn = _get_conn()
    conn.execute(
        "UPDATE transcripts SET summary_status = ? WHERE video_id = ?",
        (status, video_id),
    )
    conn.commit()
    conn.close()


def update_translation(video_id: str, translated_text: str) -> None:
    """Save LLM-translated text for a transcript."""
    conn = _get_conn()
    conn.execute(
        "UPDATE transcripts SET translated_text = ? WHERE video_id = ?",
        (translated_text, video_id),
    )
    conn.commit()
    conn.close()


# --- Settings ---

def get_settings() -> Settings:
    """Read settings. API key from Keychain (macOS) or DB fallback."""
    conn = _get_conn()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()

    data = {row["key"]: row["value"] for row in rows}

    # API key: try Keychain first, fall back to DB
    api_key = keychain.get_secret("openrouter_api_key") or ""
    if not api_key:
        api_key = data.get("openrouter_api_key", "")
        # Auto-migrate plain-text key to Keychain
        if api_key and keychain.migrate_from_db(api_key):
            _clear_db_key("openrouter_api_key")

    return Settings(
        openrouter_api_key=api_key,
        openrouter_model=data.get(
            "openrouter_model", "anthropic/claude-sonnet-4"
        ),
        whisper_model=data.get("whisper_model", "small"),
        default_language=data.get("default_language", ""),
        media_format=data.get("media_format", "mp3"),
        media_quality=data.get("media_quality", "320"),
    )


def _clear_db_key(key: str) -> None:
    """Remove a sensitive key from DB after Keychain migration."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, ""),
    )
    conn.commit()
    conn.close()
    logger.info(f"Cleared '{key}' from DB (now in Keychain)")


def save_settings(settings: Settings) -> None:
    """Write settings. API key goes to Keychain, rest to DB."""
    # Store API key in Keychain (not DB)
    if settings.openrouter_api_key:
        keychain.set_secret(
            "openrouter_api_key",
            settings.openrouter_api_key,
        )

    conn = _get_conn()
    for key, value in {
        "openrouter_api_key": "",  # never store in DB
        "openrouter_model": settings.openrouter_model,
        "whisper_model": settings.whisper_model,
        "default_language": settings.default_language,
        "media_format": settings.media_format,
        "media_quality": settings.media_quality,
    }.items():
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (key, value),
        )
    conn.commit()
    conn.close()


# --- Saved Models ---

def get_saved_models() -> list[dict]:
    """Get all saved models, favorites first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT model_id, name, is_favorite FROM saved_models ORDER BY is_favorite DESC, added_at DESC"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def add_saved_model(model_id: str, name: str) -> None:
    """Add a model to the saved list."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO saved_models (model_id, name) VALUES (?, ?)",
        (model_id, name),
    )
    conn.commit()
    conn.close()


def remove_saved_model(model_id: str) -> None:
    """Remove a model from the saved list."""
    conn = _get_conn()
    conn.execute("DELETE FROM saved_models WHERE model_id = ?", (model_id,))
    conn.commit()
    conn.close()


def set_favorite_model(model_id: str) -> None:
    """Set a model as favorite (unsets all others)."""
    conn = _get_conn()
    conn.execute("UPDATE saved_models SET is_favorite = 0")
    conn.execute(
        "UPDATE saved_models SET is_favorite = 1 WHERE model_id = ?", (model_id,)
    )
    conn.commit()
    conn.close()


# --- Collections ---

def get_collections() -> list[dict]:
    """Get all collections with transcript counts."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.id, c.name, c.created_at, COUNT(tc.video_id) as count
        FROM collections c
        LEFT JOIN transcript_collections tc ON c.id = tc.collection_id
        GROUP BY c.id
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def create_collection(name: str) -> int:
    """Create a new collection. Returns the collection ID."""
    conn = _get_conn()
    cursor = conn.execute("INSERT INTO collections (name) VALUES (?)", (name,))
    conn.commit()
    cid = cursor.lastrowid
    conn.close()
    return cid


def delete_collection(collection_id: int) -> None:
    """Delete a collection and its associations."""
    conn = _get_conn()
    conn.execute("DELETE FROM transcript_collections WHERE collection_id = ?", (collection_id,))
    conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    conn.commit()
    conn.close()


def add_to_collection(video_id: str, collection_id: int) -> None:
    """Add a transcript to a collection."""
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO transcript_collections (video_id, collection_id) VALUES (?, ?)",
        (video_id, collection_id),
    )
    conn.commit()
    conn.close()


def remove_from_collection(video_id: str, collection_id: int) -> None:
    """Remove a transcript from a collection."""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM transcript_collections WHERE video_id = ? AND collection_id = ?",
        (video_id, collection_id),
    )
    conn.commit()
    conn.close()


def get_transcript_collections(video_id: str) -> list[dict]:
    """Get collections that contain a specific transcript."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT c.id, c.name FROM collections c
        JOIN transcript_collections tc ON c.id = tc.collection_id
        WHERE tc.video_id = ?
        ORDER BY c.name
    """, (video_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_collection_transcripts(collection_id: int) -> list[dict]:
    """Get all transcripts in a collection."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT t.video_id, t.title, t.url, t.language, t.duration, t.summary,
               t.source, t.summary_status, t.created_at
        FROM transcripts t
        JOIN transcript_collections tc ON t.video_id = tc.video_id
        WHERE tc.collection_id = ?
        ORDER BY t.created_at DESC
    """, (collection_id,)).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# --- Stats ---

def get_stats() -> dict:
    """Get transcript statistics."""
    conn = _get_conn()

    total = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
    total_duration = conn.execute("SELECT COALESCE(SUM(duration), 0) FROM transcripts").fetchone()[0]

    # Per language
    lang_rows = conn.execute(
        "SELECT language, COUNT(*) as count, SUM(duration) as total_duration "
        "FROM transcripts GROUP BY language ORDER BY count DESC"
    ).fetchall()
    languages = [dict(row) for row in lang_rows]

    # Per source
    source_rows = conn.execute(
        "SELECT source, COUNT(*) as count FROM transcripts GROUP BY source"
    ).fetchall()
    sources = {row["source"]: row["count"] for row in source_rows}

    # This week
    week_count = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE created_at >= datetime('now', '-7 days')"
    ).fetchone()[0]
    week_duration = conn.execute(
        "SELECT COALESCE(SUM(duration), 0) FROM transcripts WHERE created_at >= datetime('now', '-7 days')"
    ).fetchone()[0]

    # This month
    month_count = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE created_at >= datetime('now', '-30 days')"
    ).fetchone()[0]

    # Average duration
    avg_duration = conn.execute(
        "SELECT COALESCE(AVG(duration), 0) FROM transcripts"
    ).fetchone()[0]

    conn.close()
    return {
        "total": total,
        "total_duration": total_duration,
        "languages": languages,
        "sources": sources,
        "week_count": week_count,
        "week_duration": week_duration,
        "month_count": month_count,
        "avg_duration": avg_duration,
    }


def seed_default_models() -> None:
    """Seed 5 default models if none exist."""
    conn = _get_conn()
    count = conn.execute("SELECT COUNT(*) FROM saved_models").fetchone()[0]
    if count == 0:
        defaults = [
            ("anthropic/claude-sonnet-4", "Claude Sonnet 4"),
            ("openai/gpt-4.1-mini", "GPT-4.1 Mini"),
            ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
            ("deepseek/deepseek-v3-0324", "DeepSeek V3"),
            ("meta-llama/llama-4-scout", "Llama 4 Scout"),
        ]
        for model_id, name in defaults:
            conn.execute(
                "INSERT OR IGNORE INTO saved_models (model_id, name) VALUES (?, ?)",
                (model_id, name),
            )
        conn.execute(
            "UPDATE saved_models SET is_favorite = 1 WHERE model_id = ?",
            (defaults[0][0],),
        )
        conn.commit()
    conn.close()

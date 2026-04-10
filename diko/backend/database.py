"""PostgreSQL (Supabase) database for transcript storage, search, and settings.

Migrated from SQLite. Uses psycopg2 with connection pooling.
FTS via PostgreSQL tsvector (auto-updated by trigger).
"""

import json
import logging
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

import keychain
from models import Settings, TranscriptRecord, TranscriptSegment

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Connection pool (lazy init)
_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL not set")
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=5,
            dsn=DATABASE_URL,
        )
    return _pool


@contextmanager
def _get_conn():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.autocommit = False
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def _dict_row(cursor):
    """Convert cursor row to dict."""
    if cursor.description is None:
        return None
    cols = [d[0] for d in cursor.description]
    return cols


def _fetchall_dict(cursor):
    cols = _dict_row(cursor)
    if not cols:
        return []
    return [dict(zip(cols, row)) for row in cursor.fetchall()]


def _fetchone_dict(cursor):
    cols = _dict_row(cursor)
    if not cols:
        return None
    row = cursor.fetchone()
    if not row:
        return None
    return dict(zip(cols, row))


def init_db() -> None:
    """Create tables if they don't exist. Safe to call multiple times."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transcripts (
                video_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                language TEXT NOT NULL,
                duration REAL NOT NULL,
                segments_json JSONB NOT NULL DEFAULT '[]',
                summary TEXT DEFAULT '',
                summary_status TEXT DEFAULT '',
                source TEXT DEFAULT 'whisper',
                translated_text TEXT DEFAULT '',
                channel_name TEXT DEFAULT '',
                view_count INTEGER DEFAULT 0,
                like_count INTEGER DEFAULT 0,
                categories_json JSONB DEFAULT '[]',
                category_status TEXT DEFAULT '',
                fts tsvector,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS saved_models (
                model_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                is_favorite BOOLEAN DEFAULT FALSE,
                added_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS collections (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS transcript_collections (
                video_id TEXT NOT NULL REFERENCES transcripts(video_id) ON DELETE CASCADE,
                collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
                PRIMARY KEY (video_id, collection_id)
            );

            CREATE INDEX IF NOT EXISTS idx_transcripts_fts ON transcripts USING GIN(fts);
            CREATE INDEX IF NOT EXISTS idx_transcripts_created ON transcripts(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_transcripts_language ON transcripts(language);
        """)


def save_transcript(record: TranscriptRecord) -> None:
    """Insert or update a transcript record."""
    segments_json = json.dumps(
        [{"start": s.start, "end": s.end, "text": s.text} for s in record.segments]
    )
    full_text = " ".join(s.text for s in record.segments)
    categories_json_str = json.dumps(record.categories, ensure_ascii=False) if record.categories else "[]"

    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transcripts
            (video_id, title, url, language, duration, segments_json, summary, summary_status,
             source, translated_text, channel_name, view_count, like_count, categories_json,
             category_status, fts)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s,
                    to_tsvector('simple', %s || ' ' || %s))
            ON CONFLICT (video_id) DO UPDATE SET
                title = EXCLUDED.title,
                url = EXCLUDED.url,
                language = EXCLUDED.language,
                duration = EXCLUDED.duration,
                segments_json = EXCLUDED.segments_json,
                summary = EXCLUDED.summary,
                summary_status = EXCLUDED.summary_status,
                source = EXCLUDED.source,
                translated_text = EXCLUDED.translated_text,
                channel_name = EXCLUDED.channel_name,
                view_count = EXCLUDED.view_count,
                like_count = EXCLUDED.like_count,
                categories_json = EXCLUDED.categories_json,
                category_status = EXCLUDED.category_status,
                fts = EXCLUDED.fts
        """, (
            record.video_id, record.title, record.url, record.language,
            record.duration, segments_json, record.summary, record.summary_status,
            record.source, record.translated_text, record.channel_name,
            record.view_count, record.like_count, categories_json_str,
            record.category_status, record.title, full_text,
        ))


def get_transcript(video_id: str) -> TranscriptRecord | None:
    """Get a transcript by video ID."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM transcripts WHERE video_id = %s", (video_id,))
        row = _fetchone_dict(cur)

    if not row:
        return None

    segments = [TranscriptSegment(**s) for s in (row.get("segments_json") or [])]
    categories = row.get("categories_json") or []

    return TranscriptRecord(
        video_id=row["video_id"],
        title=row["title"],
        url=row["url"],
        language=row["language"],
        duration=row["duration"],
        segments=segments,
        summary=row.get("summary", ""),
        summary_status=row.get("summary_status", ""),
        source=row.get("source", "whisper"),
        translated_text=row.get("translated_text", ""),
        channel_name=row.get("channel_name", ""),
        view_count=row.get("view_count", 0),
        like_count=row.get("like_count", 0),
        categories=categories if isinstance(categories, list) else [],
        category_status=row.get("category_status", ""),
        created_at=str(row.get("created_at", "")),
    )


def search_transcripts(query: str) -> list[dict]:
    """Full-text search across all transcripts."""
    if not query.strip():
        return []

    # Convert query words to tsquery format
    words = query.strip().split()
    tsquery = " & ".join(words)

    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT t.video_id, t.title, t.language, t.duration, t.created_at,
                   ts_headline('simple', t.title || ' ' ||
                       COALESCE((SELECT string_agg(elem->>'text', ' ')
                        FROM jsonb_array_elements(t.segments_json) AS elem), ''),
                       to_tsquery('simple', %s),
                       'StartSel=<mark>, StopSel=</mark>, MaxWords=40, MinWords=20'
                   ) as excerpt
            FROM transcripts t
            WHERE t.fts @@ to_tsquery('simple', %s)
            ORDER BY ts_rank(t.fts, to_tsquery('simple', %s)) DESC
            LIMIT 50
        """, (tsquery, tsquery, tsquery))
        return _fetchall_dict(cur)


def list_transcripts() -> list[dict]:
    """List all transcripts ordered by creation date."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT video_id, title, url, language, duration,
                   summary, source, summary_status,
                   channel_name, view_count, like_count,
                   categories_json, category_status, created_at
            FROM transcripts ORDER BY created_at DESC
        """)
        rows = _fetchall_dict(cur)

    results = []
    for row in rows:
        cats = row.pop("categories_json", [])
        row["categories"] = cats if isinstance(cats, list) else []
        results.append(row)
    return results


def delete_transcript(video_id: str) -> None:
    """Delete a transcript."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM transcripts WHERE video_id = %s", (video_id,))


def update_summary(video_id: str, summary: str, status: str = "done") -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE transcripts SET summary = %s, summary_status = %s WHERE video_id = %s",
            (summary, status, video_id),
        )


def update_summary_status(video_id: str, status: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE transcripts SET summary_status = %s WHERE video_id = %s",
            (status, video_id),
        )


def update_categories(video_id: str, categories: list[str], status: str = "done") -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE transcripts SET categories_json = %s::jsonb, category_status = %s WHERE video_id = %s",
            (json.dumps(categories, ensure_ascii=False), status, video_id),
        )


def update_category_status(video_id: str, status: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE transcripts SET category_status = %s WHERE video_id = %s",
            (status, video_id),
        )


def get_category_counts() -> list[dict]:
    """Get category names with transcript counts for filter UI."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT elem::text as name, COUNT(*) as count
            FROM transcripts, jsonb_array_elements_text(categories_json) AS elem
            WHERE category_status = 'done' AND categories_json != '[]'::jsonb
            GROUP BY elem
            ORDER BY count DESC
        """)
        return _fetchall_dict(cur)


def update_translation(video_id: str, translated_text: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE transcripts SET translated_text = %s WHERE video_id = %s",
            (translated_text, video_id),
        )


# --- Settings ---

def get_settings() -> Settings:
    """Read settings. API key from env var > Keychain > DB."""
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings")
        rows = _fetchall_dict(cur)

    data = {row["key"]: row["value"] for row in rows}

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        api_key = keychain.get_secret("openrouter_api_key") or ""
    if not api_key:
        api_key = data.get("openrouter_api_key", "")
        if api_key and keychain.migrate_from_db(api_key):
            _clear_db_key("openrouter_api_key")

    return Settings(
        openrouter_api_key=api_key,
        openrouter_model=data.get("openrouter_model", "anthropic/claude-sonnet-4"),
        whisper_model=data.get("whisper_model", "small"),
        default_language=data.get("default_language", ""),
        media_format=data.get("media_format", "mp3"),
        media_quality=data.get("media_quality", "320"),
    )


def _clear_db_key(key: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
            (key, "", ""),
        )
    logger.info(f"Cleared '{key}' from DB (now in Keychain)")


def save_settings(settings: Settings) -> None:
    """Write settings."""
    api_key_in_keychain = False
    if settings.openrouter_api_key:
        api_key_in_keychain = keychain.set_secret("openrouter_api_key", settings.openrouter_api_key)

    with _get_conn() as conn:
        cur = conn.cursor()
        for key, value in {
            "openrouter_api_key": "" if api_key_in_keychain else settings.openrouter_api_key,
            "openrouter_model": settings.openrouter_model,
            "whisper_model": settings.whisper_model,
            "default_language": settings.default_language,
            "media_format": settings.media_format,
            "media_quality": settings.media_quality,
        }.items():
            cur.execute(
                "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = %s",
                (key, value, value),
            )


# --- Saved Models ---

def get_saved_models() -> list[dict]:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT model_id, name, is_favorite FROM saved_models ORDER BY is_favorite DESC, added_at DESC"
        )
        return _fetchall_dict(cur)


def add_saved_model(model_id: str, name: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO saved_models (model_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (model_id, name),
        )


def remove_saved_model(model_id: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM saved_models WHERE model_id = %s", (model_id,))


def set_favorite_model(model_id: str) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE saved_models SET is_favorite = FALSE")
        cur.execute("UPDATE saved_models SET is_favorite = TRUE WHERE model_id = %s", (model_id,))


# --- Collections ---

def get_collections() -> list[dict]:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name, c.created_at, COUNT(tc.video_id) as count
            FROM collections c
            LEFT JOIN transcript_collections tc ON c.id = tc.collection_id
            GROUP BY c.id
            ORDER BY c.name
        """)
        return _fetchall_dict(cur)


def create_collection(name: str) -> int:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO collections (name) VALUES (%s) RETURNING id", (name,))
        return cur.fetchone()[0]


def delete_collection(collection_id: int) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM transcript_collections WHERE collection_id = %s", (collection_id,))
        cur.execute("DELETE FROM collections WHERE id = %s", (collection_id,))


def add_to_collection(video_id: str, collection_id: int) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO transcript_collections (video_id, collection_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (video_id, collection_id),
        )


def remove_from_collection(video_id: str, collection_id: int) -> None:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM transcript_collections WHERE video_id = %s AND collection_id = %s",
            (video_id, collection_id),
        )


def get_transcript_collections(video_id: str) -> list[dict]:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT c.id, c.name FROM collections c
            JOIN transcript_collections tc ON c.id = tc.collection_id
            WHERE tc.video_id = %s
            ORDER BY c.name
        """, (video_id,))
        return _fetchall_dict(cur)


def get_collection_transcripts(collection_id: int) -> list[dict]:
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT t.video_id, t.title, t.url, t.language, t.duration, t.summary,
                   t.source, t.summary_status, t.created_at
            FROM transcripts t
            JOIN transcript_collections tc ON t.video_id = tc.video_id
            WHERE tc.collection_id = %s
            ORDER BY t.created_at DESC
        """, (collection_id,))
        return _fetchall_dict(cur)


# --- Stats ---

def get_stats() -> dict:
    with _get_conn() as conn:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) FROM transcripts")
        total = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(duration), 0) FROM transcripts")
        total_duration = cur.fetchone()[0]

        cur.execute(
            "SELECT language, COUNT(*) as count, SUM(duration) as total_duration "
            "FROM transcripts GROUP BY language ORDER BY count DESC"
        )
        languages = _fetchall_dict(cur)

        cur.execute("SELECT source, COUNT(*) as count FROM transcripts GROUP BY source")
        sources = {r["source"]: r["count"] for r in _fetchall_dict(cur)}

        cur.execute("SELECT COUNT(*) FROM transcripts WHERE created_at >= NOW() - INTERVAL '7 days'")
        week_count = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(SUM(duration), 0) FROM transcripts WHERE created_at >= NOW() - INTERVAL '7 days'")
        week_duration = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM transcripts WHERE created_at >= NOW() - INTERVAL '30 days'")
        month_count = cur.fetchone()[0]

        cur.execute("SELECT COALESCE(AVG(duration), 0) FROM transcripts")
        avg_duration = cur.fetchone()[0]

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
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM saved_models")
        count = cur.fetchone()[0]
        if count == 0:
            defaults = [
                ("anthropic/claude-sonnet-4", "Claude Sonnet 4"),
                ("openai/gpt-4.1-mini", "GPT-4.1 Mini"),
                ("google/gemini-2.5-flash", "Gemini 2.5 Flash"),
                ("deepseek/deepseek-v3-0324", "DeepSeek V3"),
                ("meta-llama/llama-4-scout", "Llama 4 Scout"),
            ]
            for model_id, name in defaults:
                cur.execute(
                    "INSERT INTO saved_models (model_id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (model_id, name),
                )
            cur.execute(
                "UPDATE saved_models SET is_favorite = TRUE WHERE model_id = %s",
                (defaults[0][0],),
            )

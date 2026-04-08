# Diko

YouTube video transcription web app. Self-hosted on macOS. Lithuanian UI.
Name from Latin "dico" (I say/speak).

## Tech Stack
- Backend: Python (uv), FastAPI, faster-whisper, yt-dlp, SQLite + FTS5
- Frontend: Vite + React SPA (TypeScript, bun)
- LLM: OpenRouter API for summaries

## Database
- SQLite DB path: `~/Documents/5. AI projektai/YT_transcribe/yt_transcribe`
- Tables:
  - `transcripts` — video_id, title, url, language, duration, segments_json, summary
  - `transcripts_fts` — FTS5 full-text search index (video_id, title, content)
  - `settings` — key/value pairs (openrouter_api_key, openrouter_model, whisper_model, default_language)
  - `saved_models` — model_id, name, is_favorite (5 defaults seeded on first run)
- API key stored plain text in settings table (acceptable for local self-hosted app)
- Settings read/write via `GET/PUT /api/settings` endpoints
- Models CRUD via `/api/models/saved`, `/api/models/search` (proxies OpenRouter API)

## Commands
- `make install` — install all dependencies (uv sync + bun install)
- `make backend` — start FastAPI on :8000
- `make frontend` — start Vite dev server on :5173
- `make test` — run backend tests with pytest

## Dependencies
- ffmpeg required for yt-dlp audio extraction (`brew install ffmpeg`)
- faster-whisper requires CTranslate2 (installed via uv)

## Design System
Always read DESIGN.md before making any visual or UI decisions.
All font choices, colors, spacing, and aesthetic direction are defined there.
Do not deviate without explicit user approval.
In QA mode, flag any code that doesn't match DESIGN.md.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

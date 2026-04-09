# Repository Guidelines

## Project Structure & Module Organization
The main application lives in `diko/`. Use `diko/backend/` for the FastAPI service, SQLite access, transcription/export logic, and backend tests in `diko/backend/tests/`. Use `diko/frontend/` for the Vite + React UI; page screens are in `src/pages/`, shared UI is in `src/components/`, and static assets are in `public/`. Root-level files such as `Dockerfile`, `railway.toml`, `DESIGN.md`, and `TODOS.md` support deployment.

## Build, Test, and Development Commands
Run commands from `diko/` unless noted otherwise.

- `make install`: install backend deps with `uv` and frontend deps with `bun`.
- `make deps`: install required system tools such as `ffmpeg` and `deno` on macOS.
- `make backend`: start FastAPI on `http://localhost:8000`.
- `make frontend`: start Vite on `http://localhost:5173`.
- `make dev`: run backend and frontend together.
- `make test`: run backend pytest suite.
- `cd frontend && bun run build`: type-check and build the frontend bundle.
- `cd frontend && bun run lint`: run ESLint for TypeScript/React files.

## Coding Style & Naming Conventions
Python uses 4-space indentation, type hints, and concise module docstrings. Keep backend modules focused by responsibility, following the existing flat layout (`database.py`, `downloader.py`, `transcriber.py`). React/TypeScript files use 2-space indentation, functional components, and PascalCase filenames such as `LibraryPage.tsx`; hooks and helpers should use camelCase. Keep CSS next to the related component or page. Follow the existing ESLint config in `diko/frontend/eslint.config.js`; no separate formatter config is present, so match surrounding style closely.

## Testing Guidelines
Backend tests use `pytest` and `pytest-asyncio` with `asyncio_mode = auto`. Add tests under `diko/backend/tests/` using `test_*.py` names and keep fixtures local when feature-specific. Cover API behavior, DB interactions, and exporter/download edge cases when modifying backend code. There is no frontend test suite yet, so run `bun run build` and `bun run lint` for UI changes.

## Commit & Pull Request Guidelines
Recent history follows Conventional Commit prefixes such as `feat:`, `fix:`, and `chore:`. Keep subjects short and imperative, for example `fix: mask API key in settings response`. PRs should describe user-visible impact, list verification commands, link the related issue or task, and include screenshots for frontend changes. Call out new environment variables or deployment changes explicitly.

## Security & Configuration Tips
Do not commit secrets or local database files. Backend settings may come from the macOS Keychain or environment variables such as `DB_PATH`, `OPENROUTER_API_KEY`, `YT_COOKIES_PATH`, and frontend `VITE_API_URL`. Treat changes to download/transcription paths carefully because they affect Docker and Railway deployment.

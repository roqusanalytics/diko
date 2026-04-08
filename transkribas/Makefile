.PHONY: backend frontend dev install test deps

install:
	cd backend && uv sync
	cd frontend && bun install

backend:
	cd backend && uv run uvicorn main:app --reload --port 8000

frontend:
	cd frontend && bun run dev

test:
	cd backend && uv run pytest tests/ -v

deps:
	@command -v ffmpeg >/dev/null 2>&1 || { echo "Installing ffmpeg..."; brew install ffmpeg; }
	@command -v deno >/dev/null 2>&1 || { echo "Installing deno..."; brew install deno; }
	@echo "All system dependencies installed."

dev:
	@echo "Run in two terminals:"
	@echo "  make backend"
	@echo "  make frontend"

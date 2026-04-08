# TODOS

## YouTube Rate Limit Handling
- **What:** Add retry with exponential backoff to downloader.py for yt-dlp calls
- **Why:** YouTube can rate-limit downloads, causing silent failures or stuck progress bars
- **Context:** yt-dlp download is the first step in the pipeline. Without retry logic, a rate limit means the user sees a frozen UI with no error message. Add 3 retries with exponential backoff (2s, 4s, 8s). On final failure, send an SSE error event with a user-friendly message.
- **Depends on:** Step 2 (transcription pipeline) must be built first

## PDF Export Proof-of-Concept
- **What:** Verify weasyprint installs and works on the builder's Apple Silicon Mac with Lithuanian characters
- **Why:** weasyprint requires system deps (cairo, pango, gdk-pixbuf) that can fail to link on arm64 Macs. Lithuanian diacritics (ą, č, ę, ė, į, š, ų, ū, ž) need explicit font support.
- **Context:** Run `brew install cairo pango gdk-pixbuf && pip install weasyprint` and generate a test PDF with Lithuanian text. If it fails, fallback to reportlab (requires explicit font registration) or defer PDF export entirely. Do this BEFORE building the export feature to avoid wasted work.
- **Depends on:** Nothing. Can be done immediately as a standalone check.

## Formal Design System (DESIGN.md)
- **What:** Run /design-consultation to create a DESIGN.md with formal color tokens, spacing scale (4px base), typography rules, and component patterns
- **Why:** The wireframe CSS vars are the de facto design system but they're informal. As features are added, engineers will invent new spacing values and color shades. A DESIGN.md prevents drift.
- **Context:** Current tokens extracted from wireframe: --bg: #f0eeeb, --accent: #3b6fd4, --warm: #c07a48. Typography: Inter 300-600. Radius: 14px/7px/8px/6px. These need to be formalized with a spacing scale, named components, and usage rules.
- **Depends on:** Nothing. Can be done anytime. Recommended before adding new screens beyond the initial 3.

## Settings Snapshot at Submission Time
- **What:** Snapshot settings (whisper_model, default_language) into the job payload when submitted, not when executed
- **Why:** Settings are currently read at job execution time. If the user changes settings after submitting a job but before it runs, the job uses the new settings. This is nondeterministic behavior.
- **Context:** Discovered by Codex outside voice during CEO review. Low priority for single-user app but a correctness issue. Fix: copy relevant settings fields into the job dict at submit time in `main.py:process_jobs()`.
- **Depends on:** Nothing. Can be done independently.

## Age-Restricted/Private Video Error Handling
- **What:** Surface specific error messages for age-restricted, private, or deleted videos
- **Why:** Currently all yt-dlp errors show as generic "Invalid YouTube URL" (main.py:162). Age-restricted videos need cookies, private videos are inaccessible. Users deserve a clear explanation.
- **Context:** Parse yt_dlp.DownloadError message to detect specific error types and return appropriate 4xx status codes with Lithuanian error messages.
- **Depends on:** Nothing. Can be done independently.

## Transcript List Virtualization
- **What:** Virtualize the transcript segment list for long videos (10K+ segments)
- **Why:** Currently all segments render in the DOM (TranscribePage.tsx:371). A 5-hour video has ~10K segments, which slows the UI.
- **Context:** Use react-window or similar for virtual scrolling. Only render visible segments. Keep click-to-seek behavior.
- **Depends on:** Nothing. Can be done independently.

## VTT Parser Fallback Tests
- **What:** Add regression tests for edge cases in VTT parsing from YouTube subtitle extraction
- **Why:** yt-dlp can return unexpected VTT formats (empty, missing timestamps, non-standard encoding). get_captions() must gracefully fallback to Whisper in all cases.
- **Context:** Collect real-world VTT edge cases from YouTube and write tests that verify graceful degradation. The parser should never crash, only return None to trigger Whisper fallback.
- **Depends on:** YouTube caption extraction feature (must be implemented first)

## Dark Mode
- **What:** Design and implement dark mode color palette with a settings toggle
- **Why:** User cares about aesthetics (8 design iterations). Dark mode is expected in modern apps. The warm linen aesthetic needs a dark counterpart that preserves the warmth.
- **Context:** Light mode uses #f0eeeb (warm linen) as base. Dark mode should NOT be pure black, more like a warm charcoal (#1e1e24 range). Needs its own 8-iteration design pass. Deferred from v1 to keep scope manageable.
- **Depends on:** Formal design system (CSS variables make this easier)

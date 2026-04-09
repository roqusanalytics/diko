"""Export transcripts to SRT and PDF formats."""

from models import TranscriptSegment


def to_srt(segments: list[TranscriptSegment]) -> str:
    """Convert segments to SRT subtitle format."""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = _format_srt_time(seg.start)
        end = _format_srt_time(seg.end)
        lines.append(f"{i}\n{start} --> {end}\n{seg.text}\n")
    return "\n".join(lines)


def _format_srt_time(seconds: float) -> str:
    """Format seconds as SRT timestamp: HH:MM:SS,mmm"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_pdf_html(title: str, segments: list[TranscriptSegment], summary: str = "") -> str:
    """Generate HTML for PDF rendering via weasyprint."""
    lines_html = ""
    for seg in segments:
        m = int(seg.start // 60)
        s = int(seg.start % 60)
        time_str = f"{m}:{s:02d}"
        lines_html += f'<div class="line"><span class="time">{time_str}</span><span class="text">{seg.text}</span></div>\n'

    summary_section = ""
    if summary:
        summary_section = f'<div class="summary"><h2>AI Santrauka</h2><p>{summary}</p></div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: 'Inter', Arial, sans-serif; font-size: 11pt; color: #1c1c1a; margin: 40px; }}
  h1 {{ font-size: 18pt; margin-bottom: 8px; }}
  .summary {{ background: #fcf3eb; padding: 12px 16px; border-radius: 8px; margin: 16px 0; }}
  .summary h2 {{ font-size: 10pt; color: #c07a48; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 6px; }}
  .summary p {{ font-size: 11pt; line-height: 1.6; }}
  .line {{ display: flex; gap: 12px; padding: 4px 0; border-bottom: 1px solid #eee; }}
  .time {{ color: #3b6fd4; font-size: 10pt; min-width: 40px; font-variant-numeric: tabular-nums; }}
  .text {{ font-size: 11pt; line-height: 1.5; }}
  .footer {{ margin-top: 24px; font-size: 9pt; color: #9c9a96; text-align: center; }}
</style>
</head>
<body>
<h1>{title}</h1>
{summary_section}
{lines_html}
<div class="footer">Sugeneruota su Diko</div>
</body>
</html>"""

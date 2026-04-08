"""AI summary generation via OpenRouter API."""

import httpx

from models import SummaryResult


async def summarize(text: str, api_key: str, model: str = "anthropic/claude-sonnet-4") -> SummaryResult:
    """Generate a summary of transcript text using OpenRouter."""
    if not api_key:
        raise ValueError("No OpenRouter API key configured")

    # Truncate very long transcripts to ~12k tokens (~48k chars)
    if len(text) > 48000:
        text = text[:48000] + "..."

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Esi ekspertinis turinio analitikas. Pateik išsamų video transkripto TLDR lietuvių kalba.\n\n"
                            "Struktūra:\n"
                            "**Santrauka** — 2-3 sakiniai apie pagrindinę video temą ir kontekstą.\n\n"
                            "**Esminiai punktai:**\n"
                            "- Išskirkite 5-10 svarbiausių teiginių ar įžvalgų kaip bullet points.\n\n"
                            "**Vertingiausi metodai/patarimai:**\n"
                            "- Konkretūs veiksmai, technikos ar strategijos, kurias žiūrovas gali pritaikyti.\n\n"
                            "**Svarbios detalės:**\n"
                            "- Skaičiai, tyrimai, pavyzdžiai ar citatos, kurios pagrindžia pagrindinius teiginius.\n\n"
                            "Rašyk TIK lietuviškai, nepriklausomai nuo transkripto kalbos. "
                            "Būk konkretus ir informatyvus — vengk bendrybių."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                "max_tokens": 1500,
            },
        )
        response.raise_for_status()
        data = response.json()
        summary_text = data["choices"][0]["message"]["content"]

    return SummaryResult(text=summary_text, model=model)

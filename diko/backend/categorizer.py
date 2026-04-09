"""Auto-categorization of transcripts using LLM. Parses categories from summary response."""

import json
import logging

logger = logging.getLogger(__name__)

# Fixed taxonomy — LLM picks 1-3 from this list.
# English keys used for storage, Lithuanian values for UI display.
CATEGORIES = [
    "AI",
    "Programming",
    "Business",
    "Science",
    "Education",
    "Design",
    "Marketing",
    "Finance",
    "Health",
    "Music",
    "Gaming",
    "News",
    "Philosophy",
    "Productivity",
    "Other",
]

# English → Lithuanian mapping for UI
CATEGORY_LABELS_LT = {
    "AI": "DI",
    "Programming": "Programavimas",
    "Business": "Verslas",
    "Science": "Mokslas",
    "Education": "Švietimas",
    "Design": "Dizainas",
    "Marketing": "Rinkodara",
    "Finance": "Finansai",
    "Health": "Sveikata",
    "Music": "Muzika",
    "Gaming": "Žaidimai",
    "News": "Naujienos",
    "Philosophy": "Filosofija",
    "Productivity": "Produktyvumas",
    "Other": "Kita",
}

# Category instruction appended to the summary system prompt
CATEGORY_INSTRUCTION = (
    "\n\nPo santraukos, naujoje eilutėje, pateik JSON masyvą su 1-3 kategorijomis iš šio sąrašo "
    "(naudok TIKTAI šiuos angliškus pavadinimus): "
    + json.dumps(CATEGORIES)
    + '\nFormatas: CATEGORIES: ["Category1", "Category2"]'
    "\nPasirink tinkamiausias kategorijas pagal video turinį."
)


def parse_categories_from_response(response_text: str) -> tuple[str, list[str]]:
    """Parse summary text and categories from a combined LLM response.

    Returns (clean_summary, categories_list).
    The LLM appends CATEGORIES: [...] at the end of the summary.
    """
    categories: list[str] = []
    summary = response_text

    # Look for CATEGORIES: [...] pattern at the end
    marker = "CATEGORIES:"
    marker_idx = response_text.rfind(marker)
    if marker_idx != -1:
        summary = response_text[:marker_idx].rstrip()
        json_part = response_text[marker_idx + len(marker):].strip()

        try:
            parsed = json.loads(json_part)
            if isinstance(parsed, list):
                # Validate against taxonomy
                categories = [c for c in parsed if c in CATEGORIES]
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse categories JSON: {json_part[:100]}")

    # Fallback: if no valid categories found, assign "Other"
    if not categories:
        categories = ["Other"]

    return summary, categories

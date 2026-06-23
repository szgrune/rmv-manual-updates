"""
Derive page-level citations for quoted bullets.

Every bullet in the change data is a direct quote ending in an attribution like
`(2026 Massachusetts Driver's Manual)`. This module finds the physical PDF page
that quote appears on so the frontend can deep-link to it (`#page=N`).

Matching is done against the *actual* per-page PDF text (via PyMuPDF), not the
DB `body_text` — the DB buckets a section's whole body under its start page, so
it can't pin a quote to the page it physically appears on. The returned `page`
is the 1-based physical page used by PDF viewers' `#page=` anchor.

Matching is fuzzy-ish: text is normalized (curly quotes/apostrophes folded,
non-alphanumerics collapsed) and we try progressively shorter prefixes, with a
fallback for quotes broken across a page boundary.
"""

import re
from pathlib import Path

import fitz  # pymupdf

PROJECT_ROOT = Path(__file__).parent.parent.parent
MANUALS_DIR = PROJECT_ROOT / "Manuals"

# Default source-PDF filename pattern; the Spanish build overrides this with
# "Drivers_Manual_Spanish_{year}.pdf" and a different manuals directory.
DEFAULT_FILENAME_PATTERN = "Drivers_Manual_{year}.pdf"

# The attribution that ends every quoted bullet, e.g. "(2023 Massachusetts ...)".
# Located anywhere in the bullet; the quote is whatever precedes it. The wrapping
# quotation marks are optional because the model sometimes omits them when writing
# the surrounding content in another language (e.g. Spanish), even though the
# quoted text itself is still verbatim from the manual.
_ATTR_RE = re.compile(r'\((\d{4})\s+Massachusetts', re.I)


def _norm(text: str) -> str:
    text = (text.replace("“", '"').replace("”", '"')
                .replace("‘", "'").replace("’", "'"))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _manual_path(year: int, manuals_dir: Path = MANUALS_DIR,
                 filename_pattern: str = DEFAULT_FILENAME_PATTERN) -> Path:
    return manuals_dir / filename_pattern.format(year=year)


def build_page_index(years, manuals_dir: Path = MANUALS_DIR,
                     filename_pattern: str = DEFAULT_FILENAME_PATTERN) -> dict:
    """{year: [normalized_text_for_physical_page_0, page_1, ...]} for each PDF found."""
    index = {}
    for year in years:
        path = _manual_path(year, manuals_dir, filename_pattern)
        if not path.exists():
            continue
        doc = fitz.open(path)
        index[year] = [_norm(doc[i].get_text()) for i in range(len(doc))]
        doc.close()
    return index


def _find_page(index: dict, year: int, quote: str):
    """Return the 1-based physical page for `quote`, or None."""
    pages = index.get(year)
    if not pages:
        return None
    nq = _norm(quote)
    if not nq:
        return None

    # 1) Prefer a single-page match, longest prefix first.
    for frac in (1.0, 0.7, 0.5, 0.35):
        sub = nq[: max(20, int(len(nq) * frac))]
        for i, text in enumerate(pages):
            if sub in text:
                return i + 1

    # 2) Fallback: the quote is split across a page boundary.
    sub = nq[: max(20, int(len(nq) * 0.6))]
    for i in range(len(pages) - 1):
        if sub in (pages[i] + " " + pages[i + 1]):
            return i + 1

    return None


def citation_for_bullet(index: dict, bullet: str):
    """Return {"year", "page"} for a quoted bullet, or None if unmatched."""
    m = _ATTR_RE.search(bullet)
    if not m:
        return None
    year = int(m.group(1))
    # Everything before the attribution is the quote; drop any wrapping quotes.
    quote = bullet[: m.start()].strip().strip('"“”').strip()
    if len(quote) < 12:
        return None
    page = _find_page(index, year, quote)
    if page is None:
        return None
    return {"year": year, "page": page}


def enrich(section: dict, index: dict) -> int:
    """
    Attach a `citations` list (aligned with `bullets`) to `section` in place.
    Returns the number of bullets that were successfully matched to a page.
    """
    bullets = section.get("bullets") or []
    citations = [citation_for_bullet(index, b) for b in bullets]
    section["citations"] = citations
    return sum(1 for c in citations if c)

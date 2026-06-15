#!/usr/bin/env python3
"""
Derive a coarse, editable subtopic outline for the web app.

READ-ONLY against data/manuals.db — this script never writes to the database and
never re-runs the AI analysis. It inspects the latest manual's section headings,
filters out body-text noise, trims each heading to <=3 words, and keeps only the
headings that actually contain a change result (matched by citation page). The
result is written to web/data/subtopics.json, which is then meant to be
hand-curated: edit a title there, reload the page, done.

Run once (and again only when a new manual year is added):

    python3 scripts/derive_subtopics.py
"""

import json
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "manuals.db"
WEB_DATA = ROOT / "web" / "data"
MANIFEST = WEB_DATA / "manifest.json"
OUT_PATH = WEB_DATA / "subtopics.json"

MAX_HEADING_WORDS = 3   # hard cap on the rendered heading length
MAX_SOURCE_WORDS = 6    # a "heading" longer than this in the PDF is really a sentence
MAX_SOURCE_CHARS = 45


def looks_like_heading(title: str) -> bool:
    """Heuristic: keep clean section headings, drop extracted body-text fragments."""
    t = title.strip()
    if not t:
        return False
    if not re.match(r"^[A-Z]", t):          # headings start capitalized
        return False
    if t.endswith((".", ",", ":", ";")):    # sentences / list intros
        return False
    if any(ch in t for ch in "•(){}[]–—/"):  # bullets, asides, ranges, slashes
        return False
    if re.search(r"\d", t):                   # page nums, phone nums, fees, etc.
        return False
    words = t.split()
    if len(words) > MAX_SOURCE_WORDS or len(t) > MAX_SOURCE_CHARS:
        return False
    return True


def trim_words(title: str) -> str:
    return " ".join(title.split()[:MAX_HEADING_WORDS])


def latest_year() -> int:
    return json.loads(MANIFEST.read_text())["latest_year"]


def candidate_headings(conn, year: int):
    """Ordered clean heading candidates per chapter: {chapter_num: [(page, title)]}."""
    rows = conn.execute(
        "SELECT chapter_num, title, page FROM sections "
        "WHERE year = ? ORDER BY chapter_num, page, id",
        (year,),
    ).fetchall()

    by_chapter: dict[int, list[tuple[int, str]]] = {}
    seen: set[tuple[int, str]] = set()
    for chapter_num, title, page in rows:
        if not looks_like_heading(title):
            continue
        trimmed = trim_words(title)
        key = (chapter_num, trimmed.lower())
        if key in seen:
            continue
        seen.add(key)
        by_chapter.setdefault(chapter_num, []).append((page, trimmed))
    return by_chapter


def result_pages():
    """Min citation page for every change result, grouped by chapter: {chapter_num: [page]}."""
    pages: dict[int, list[int]] = {}
    for f in sorted(WEB_DATA.glob("changes_*_to_*.json")):
        data = json.loads(f.read_text())
        for sec in data.get("sections", []):
            cits = [c.get("page") for c in (sec.get("citations") or []) if c and c.get("page")]
            if not cits:
                continue
            chapter_num = sec.get("chapter_num")
            if chapter_num is None:
                continue
            pages.setdefault(chapter_num, []).append(min(cits))
    return pages


def bucket_page(page: int, headings: list[tuple[int, str]]):
    """The heading whose page is the greatest <= the result page (None if before all)."""
    chosen = None
    for hp, _title in headings:  # headings are page-sorted
        if hp <= page:
            chosen = (hp, _title)
        else:
            break
    return chosen


def main():
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        year = latest_year()
        cand = candidate_headings(conn, year)
        pages = result_pages()

        out = []
        for chapter_num, headings in cand.items():
            used = set()
            for page in pages.get(chapter_num, []):
                hit = bucket_page(page, headings)
                if hit:
                    used.add(hit)
            for hp, title in sorted(used):
                out.append({"chapter_num": chapter_num, "page": hp, "title": title})

        out.sort(key=lambda e: (e["chapter_num"], e["page"]))
        OUT_PATH.write_text(json.dumps(out, indent=2) + "\n")
        print(f"Wrote {len(out)} subtopics to {OUT_PATH.relative_to(ROOT)}")
        for e in out:
            print(f"  ch{e['chapter_num']}  p{e['page']:>3}  {e['title']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

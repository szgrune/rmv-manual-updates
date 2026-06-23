"""
Build the SPANISH edition of the Driver's Manual Updates app.

This is a parallel run of the exact same pipeline used for the English build
(extract → analyze via the LLM → export JSON + page citations), pointed at the
two Spanish PDFs in web/manuals_spanish/ and comparing 2019 → 2023.

Why a separate orchestrator (rather than reusing build.sh):
  - The English DB is keyed by year and already contains a 2023 entry, so the
    Spanish data must live in its own SQLite store (data/manuals_spanish.db).
  - Spanish images, output JSON, manifest, and overrides all get their own
    namespaces so the English build is never touched.

The model-generated fields (overview, titles, descriptions) are written in
Spanish; bullets remain verbatim Spanish quotes copied from the PDFs.

Coverage accumulates across runs: each invocation appends one analysis run (unless
--reset) and the published change set is the MERGE of all runs (see lib/merge.py),
so repeated builds keep finding and adding new genuine changes. Manual overrides are
re-applied on top every time, and existing change ids are stable across appended runs
so override keys keep matching.

Usage:
    ANTHROPIC_API_KEY=sk-... python3 scripts/build_spanish.py              # append 1 run, re-merge
    ANTHROPIC_API_KEY=sk-... python3 scripts/build_spanish.py --runs 3     # append 3 runs at once
    ANTHROPIC_API_KEY=sk-... python3 scripts/build_spanish.py --reset      # discard prior runs, start over
    python3 scripts/build_spanish.py --no-analyze                          # extraction only (no API)
"""

import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

# ── Spanish profile ─────────────────────────────────────────────────────────────
OLD_YEAR = 2019
NEW_YEAR = 2023
LANGUAGE = "Spanish"

MANUALS_DIR = PROJECT_ROOT / "web" / "manuals_spanish"
FILENAME_PATTERN = "Drivers_Manual_Spanish_{year}.pdf"
IMAGES_BASE_DIR = PROJECT_ROOT / "web" / "images_spanish"
IMAGES_URL_PREFIX = "images_spanish"

DB_PATH = PROJECT_ROOT / "data" / "manuals_spanish.db"
OVERRIDES_PATH = PROJECT_ROOT / "data" / "overrides_spanish.json"
BASELINE_PATH = PROJECT_ROOT / "data" / ".export_baseline_spanish.json"

OUTPUT_SUFFIX = "_spanish"
MANIFEST_NAME = "manifest_spanish.json"
SUBTOPICS_NAME = "subtopics_spanish.json"
WEB_DATA_DIR = PROJECT_ROOT / "web" / "data"

# Spanish labels for the synthetic chapter buckets the pipeline creates.
OTHER_CHAPTER_LABEL = "Otras Actualizaciones"
REMOVED_CHAPTER_LABEL = "Ya No Se Incluye"

# CRITICAL: point lib.db at the Spanish store BEFORE importing it (db.py reads
# MANUALS_DB at import time).
os.environ["MANUALS_DB"] = str(DB_PATH)

from lib import db as database          # noqa: E402
from lib.pdf_extractor import extract_manual  # noqa: E402
from lib.llm_client import get_analyzer  # noqa: E402
import analyze_changes as ac            # noqa: E402
import export_json as ej                # noqa: E402


def year_from_filename(path: Path) -> int | None:
    import re
    m = re.search(r"(\d{4})", path.stem)
    return int(m.group(1)) if m else None


def extract() -> None:
    database.init_db()
    pdfs = sorted(MANUALS_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {MANUALS_DIR}")
        sys.exit(1)

    print(f"Found {len(pdfs)} Spanish PDFs in {MANUALS_DIR}")
    for pdf_path in pdfs:
        year = year_from_filename(pdf_path)
        if year is None:
            print(f"  Skipping {pdf_path.name}: cannot parse year")
            continue
        if database.year_exists(year):
            print(f"  Year {year} already in Spanish DB — re-extracting")
            database.delete_year_data(year)
        print(f"\n[{year}] Extracting {pdf_path.name}...")
        images_dir = IMAGES_BASE_DIR / str(year)
        sections = extract_manual(pdf_path, images_dir, year, url_prefix=IMAGES_URL_PREFIX)
        database.insert_manual(year)
        for sec in sections:
            sec_id = database.insert_section(
                year=year,
                chapter_num=sec.chapter_num,
                chapter_title=sec.chapter_title,
                section_key=sec.section_key,
                title=sec.title,
                page=sec.page,
                body_text=sec.body_text,
            )
            for img in sec.images:
                database.insert_image(section_id=sec_id, src_path=img.src_path)
        print(f"  ✓ Year {year} written to Spanish DB")

    print(f"\n✓ Extraction complete. Years in Spanish DB: {database.get_all_manual_years()}")


def analyze(runs: int = 1, reset: bool = False) -> None:
    analyzer = get_analyzer()
    print(f"\nAnalyzer backend: {type(analyzer).__name__}")
    ac.analyze_pair(
        OLD_YEAR,
        NEW_YEAR,
        analyzer,
        runs=runs,
        reset=reset,
        language=LANGUAGE,
        other_chapter_label=OTHER_CHAPTER_LABEL,
        removed_chapter_label=REMOVED_CHAPTER_LABEL,
        inclusive=True,
    )


def export() -> None:
    ej.export_all(
        suffix=OUTPUT_SUFFIX,
        manifest_name=MANIFEST_NAME,
        overrides_path=OVERRIDES_PATH,
        baseline_path=BASELINE_PATH,
        citation_manuals_dir=MANUALS_DIR,
        citation_filename_pattern=FILENAME_PATTERN,
    )


def derive_subtopics() -> None:
    """
    Best-effort Spanish subtopic outline (web/data/subtopics_spanish.json),
    reusing derive_subtopics.py's pure heuristics but scoped to the Spanish DB
    and the Spanish changes file. Non-fatal — the app degrades to chapter-only
    grouping if this is missing.
    """
    import json
    try:
        from derive_subtopics import candidate_headings, bucket_page

        changes_file = WEB_DATA_DIR / f"changes_{OLD_YEAR}_to_{NEW_YEAR}{OUTPUT_SUFFIX}.json"
        if not changes_file.exists():
            print("  (skipping subtopics — Spanish changes file not found)")
            return

        # Min citation page per change, grouped by chapter.
        result_pages: dict[int, list[int]] = {}
        data = json.loads(changes_file.read_text())
        for sec in data.get("sections", []):
            cits = [c.get("page") for c in (sec.get("citations") or []) if c and c.get("page")]
            chapter_num = sec.get("chapter_num")
            if cits and chapter_num is not None:
                result_pages.setdefault(chapter_num, []).append(min(cits))

        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            cand = candidate_headings(conn, NEW_YEAR)
        finally:
            conn.close()

        out = []
        for chapter_num, headings in cand.items():
            used = set()
            for page in result_pages.get(chapter_num, []):
                hit = bucket_page(page, headings)
                if hit:
                    used.add(hit)
            for hp, title in sorted(used):
                out.append({"chapter_num": chapter_num, "page": hp, "title": title})
        out.sort(key=lambda e: (e["chapter_num"], e["page"]))

        (WEB_DATA_DIR / SUBTOPICS_NAME).write_text(json.dumps(out, indent=2) + "\n")
        print(f"  ✓ {SUBTOPICS_NAME} ({len(out)} subtopics)")
    except Exception as e:
        print(f"  (subtopics skipped: {e})")


def _arg_int(flag, default):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1])
            except ValueError:
                pass
    return default


def main():
    no_analyze = "--no-analyze" in sys.argv
    runs = _arg_int("--runs", 1)
    reset = "--reset" in sys.argv

    print("=== Spanish Driver's Manual Updates — Build ===\n")
    print("[1/4] Extracting Spanish PDFs...")
    extract()

    if no_analyze:
        print("\n--no-analyze given; stopping after extraction.")
        return

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nERROR: ANTHROPIC_API_KEY is not set — cannot run the analysis step.")
        print("Set it and re-run: ANTHROPIC_API_KEY=sk-... python3 scripts/build_spanish.py")
        sys.exit(1)

    print(f"\n[2/4] Analyzing changes (2019 → 2023, Spanish; runs={runs}, reset={reset})...")
    analyze(runs=runs, reset=reset)

    print("\n[3/4] Exporting Spanish JSON...")
    export()

    print("\n[4/4] Deriving Spanish subtopics...")
    derive_subtopics()

    print("\n=== Spanish build complete. ===")
    print(f"  Output: web/data/changes_{OLD_YEAR}_to_{NEW_YEAR}{OUTPUT_SUFFIX}.json")
    print("  Serve with: cd web && python3 -m http.server 8080  (then toggle ES)")


if __name__ == "__main__":
    main()

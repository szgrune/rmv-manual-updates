"""
Add a new Driver's Manual PDF to the system.

Workflow:
  1. Extract text + images from the new PDF
  2. Run change analysis against all existing years
  3. Export updated JSON files + manifest

Usage:
    python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf
    ANALYZER_BACKEND=openai python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database
from lib.pdf_extractor import extract_manual
from lib.llm_client import get_analyzer
import analyze_changes as ac
import export_json as ej

IMAGES_BASE_DIR = PROJECT_ROOT / "web" / "images"


def year_from_filename(path: Path) -> int | None:
    m = re.search(r"(\d{4})", path.stem)
    return int(m.group(1)) if m else None


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/update_manual.py <path/to/Drivers_Manual_YYYY.pdf>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).resolve()
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    new_year = year_from_filename(pdf_path)
    if new_year is None:
        print(f"Cannot parse a 4-digit year from filename: {pdf_path.name}")
        print("Rename the file to include the year, e.g. Drivers_Manual_2028.pdf")
        sys.exit(1)

    database.init_db()
    existing_years = database.get_all_manual_years()

    if new_year in existing_years:
        print(f"Year {new_year} already exists in the database.")
        print("Use extract_pdfs.py --force to re-extract, then re-run this script.")
        sys.exit(1)

    print(f"=== Adding {new_year} manual ===\n")

    # Step 1: Extract
    print(f"[1/3] Extracting {pdf_path.name}...")
    images_dir = IMAGES_BASE_DIR / str(new_year)
    sections = extract_manual(pdf_path, images_dir, new_year)

    database.insert_manual(new_year)
    for sec in sections:
        sec_id = database.insert_section(
            year=new_year,
            chapter_num=sec.chapter_num,
            chapter_title=sec.chapter_title,
            section_key=sec.section_key,
            title=sec.title,
            page=sec.page,
            body_text=sec.body_text,
        )
        for img in sec.images:
            database.insert_image(section_id=sec_id, src_path=img.src_path)

    all_years = database.get_all_manual_years()
    latest = max(all_years)
    prior_years = [y for y in all_years if y != latest]
    print(f"  ✓ Year {new_year} extracted ({len(sections)} sections)")

    # Step 2: Analyze
    print(f"\n[2/3] Analyzing changes for {[f'{y}→{latest}' for y in prior_years]}...")
    analyzer = get_analyzer()
    print(f"  Analyzer: {type(analyzer).__name__}")

    for old_year in prior_years:
        ac.analyze_pair(old_year, latest, analyzer, runs=1, reset=True)

    # Step 3: Export
    print("\n[3/3] Exporting JSON files...")
    ej.export_all()

    print(f"\n=== Done. Year {new_year} is now live in the web app. ===")
    print("Serve with: cd web && python3 -m http.server 8080")


if __name__ == "__main__":
    main()

"""
Extract text and images from all Driver's Manual PDFs in the Manuals/ folder
and write the results to the SQLite database.

Usage:
    python3 scripts/extract_pdfs.py
"""

import sys
from pathlib import Path

# Allow running from project root or scripts/ directory
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database
from lib.pdf_extractor import extract_manual

MANUALS_DIR = PROJECT_ROOT / "Manuals"
IMAGES_BASE_DIR = PROJECT_ROOT / "web" / "images"


def year_from_filename(path: Path) -> int | None:
    """Parse year from filenames like Drivers_Manual_2026.pdf"""
    import re
    m = re.search(r"(\d{4})", path.stem)
    return int(m.group(1)) if m else None


def extract_one_year(pdf_path: Path, force: bool = False) -> None:
    year = year_from_filename(pdf_path)
    if year is None:
        print(f"Skipping {pdf_path.name}: cannot parse year from filename")
        return

    if database.year_exists(year) and not force:
        print(f"  Year {year} already in DB — skipping (use --force to re-extract)")
        return

    if database.year_exists(year) and force:
        print(f"  Re-extracting year {year} (--force)")
        database.delete_year_data(year)

    print(f"\n[{year}] Extracting {pdf_path.name}...")
    images_dir = IMAGES_BASE_DIR / str(year)
    sections = extract_manual(pdf_path, images_dir, year)

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
            database.insert_image(
                section_id=sec_id,
                src_path=img.src_path,
            )

    print(f"  ✓ Year {year} written to DB")


def main():
    force = "--force" in sys.argv
    database.init_db()

    pdf_files = sorted(MANUALS_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"No PDFs found in {MANUALS_DIR}")
        sys.exit(1)

    print(f"Found {len(pdf_files)} PDFs in {MANUALS_DIR}")
    for pdf_path in pdf_files:
        extract_one_year(pdf_path, force=force)

    years = database.get_all_manual_years()
    print(f"\n✓ Extraction complete. Years in DB: {years}")


if __name__ == "__main__":
    main()

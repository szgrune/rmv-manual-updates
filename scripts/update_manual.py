"""
Add a new Driver's Manual PDF to the system.

Two modes:
  newest  The uploaded manual is the new latest edition. Re-analyze every prior
          year against it, re-point all "Changes Since YEAR" pages to it, and
          remove now-stale change files that targeted the previous latest.
  old     The uploaded manual is an older edition. Run the single comparison
          (uploaded year → current latest) so its "Changes Since YEAR" page
          appears, without re-analyzing the other pairs.

When run from the CLI without an explicit mode, the mode is inferred from the
year (newer than the current latest → newest, otherwise → old).

Usage:
    python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf
    python3 scripts/update_manual.py Manuals/Drivers_Manual_2010.pdf old
    ANALYZER_BACKEND=openai python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf newest
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
WEB_DATA_DIR = PROJECT_ROOT / "web" / "data"

# All manual PDFs must follow this naming convention so the year can be parsed
# reliably and duplicates can be detected.
FILENAME_RE = re.compile(r"^Drivers_Manual_(\d{4})\.pdf$")
NAMING_HELP = (
    "PDF files must be named 'Drivers_Manual_<YYYY>.pdf' "
    "(e.g. Drivers_Manual_2028.pdf)."
)


def year_from_filename(path: Path) -> int | None:
    """Loose year parse (any 4 digits). Kept for back-compat callers."""
    m = re.search(r"(\d{4})", path.stem)
    return int(m.group(1)) if m else None


def validate_filename(path: Path) -> int:
    """Enforce the naming convention and return the parsed year, or raise."""
    m = FILENAME_RE.match(path.name)
    if not m:
        raise ValueError(f"Invalid file name '{path.name}'. {NAMING_HELP}")
    return int(m.group(1))


def _cleanup_stale_change_files(latest: int, log=print) -> None:
    """Remove English change files that no longer target the current latest year
    (e.g. changes_2007_to_2026.json once the latest becomes 2028)."""
    keep_suffix = f"_to_{latest}.json"
    for f in WEB_DATA_DIR.glob("changes_*_to_*.json"):
        if f.name.endswith("_spanish.json"):
            continue
        if not f.name.endswith(keep_suffix):
            f.unlink()
            log(f"  ↳ removed stale {f.name}")


def add_manual(pdf_path, mode: str | None = None, log=print) -> dict:
    """Ingest a new manual PDF and regenerate the site data.

    Raises ValueError for any validation problem (bad name, duplicate year,
    mode/year mismatch). Returns a summary dict on success. `log` is a callable
    used for progress output (defaults to print; the admin passes a collector).
    """
    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        raise ValueError(f"File not found: {pdf_path}")

    new_year = validate_filename(pdf_path)

    database.init_db()
    existing_years = database.get_all_manual_years()
    if new_year in existing_years:
        raise ValueError("Error - that manual is already in the database")

    current_latest = max(existing_years) if existing_years else None
    inferred = "newest" if (current_latest is None or new_year > current_latest) else "old"
    if mode is None:
        mode = inferred
    if mode not in ("old", "newest"):
        raise ValueError(f"Unknown mode '{mode}'. Use 'old' or 'newest'.")

    # Guard against a mode that contradicts the year, so the operator gets a
    # clear message instead of a surprising result.
    if mode == "newest" and current_latest is not None and new_year <= current_latest:
        raise ValueError(
            f"Year {new_year} is not newer than the current latest "
            f"({current_latest}). Choose 'Old Manual'."
        )
    if mode == "old":
        if current_latest is None:
            raise ValueError(
                "There is no existing manual to compare against. "
                "Upload the newest manual first."
            )
        if new_year > current_latest:
            raise ValueError(
                f"Year {new_year} is newer than the current latest "
                f"({current_latest}). Choose 'Newest Manual'."
            )

    log(f"=== Adding {new_year} manual (mode: {mode}) ===")

    # Step 1: Extract
    log(f"[1/3] Extracting {pdf_path.name}...")
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
    log(f"  ✓ Year {new_year} extracted ({len(sections)} sections)")

    # Step 2: Analyze
    analyzer = get_analyzer()
    log(f"  Analyzer: {type(analyzer).__name__}")

    if mode == "newest":
        prior_years = [y for y in all_years if y != latest]
        log(f"[2/3] Analyzing {[f'{y}→{latest}' for y in prior_years]}...")
        for old_year in prior_years:
            ac.analyze_pair(old_year, latest, analyzer, runs=1, reset=True)
    else:  # old
        log(f"[2/3] Analyzing {new_year}→{latest}...")
        ac.analyze_pair(new_year, latest, analyzer, runs=1, reset=True)

    # Step 3: Export
    log("[3/3] Exporting JSON files...")
    ej.export_all()

    # When a newer latest arrives, files that targeted the old latest are stale.
    if mode == "newest" and current_latest is not None and current_latest != latest:
        _cleanup_stale_change_files(latest, log)

    log(f"=== Done. Year {new_year} is now live in the web app. ===")
    return {
        "year": new_year,
        "mode": mode,
        "latest": latest,
        "sections": len(sections),
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/update_manual.py "
              "<path/to/Drivers_Manual_YYYY.pdf> [old|newest]")
        sys.exit(1)

    mode = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        add_manual(sys.argv[1], mode)
    except ValueError as e:
        print(e)
        sys.exit(1)

    print("Serve with: cd web && python3 -m http.server 8080")


if __name__ == "__main__":
    main()

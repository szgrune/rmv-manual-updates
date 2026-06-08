"""
Export all change analyses from SQLite to web/data/*.json files.
Also writes web/data/manifest.json for the frontend dropdown.

Manual edits are preserved. Before each file is overwritten, any hand-edits you
made to it are captured into data/overrides.json; those overrides are then
re-applied on top of the freshly generated data so your corrections are
permanent — even after re-analyzing new PDFs. See lib/overrides.py.

Usage:
    python3 scripts/export_json.py
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database
from lib import overrides as ov
from lib import citations as cite

WEB_DATA_DIR = PROJECT_ROOT / "web" / "data"


def _read_existing(path: Path) -> dict | None:
    """Read a change file currently on disk (may contain manual edits)."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        print(f"  WARNING: {path.name} on disk is not valid JSON — cannot capture "
              f"edits from it this run. Existing overrides are still applied.")
        return None


def export_all() -> None:
    WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

    years = database.get_all_manual_years()
    if not years:
        print("No years in DB. Run extract_pdfs.py first.")
        sys.exit(1)

    latest = years[-1]
    prior_years = years[:-1]

    # Write manifest.json
    manifest = {
        "manual_years": years,
        "latest_year": latest,
    }
    manifest_path = WEB_DATA_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"  ✓ manifest.json  (years: {years}, latest: {latest})")

    overrides = ov.load_overrides()
    baseline = ov.load_baseline()

    # Page index for deriving per-quote PDF citations (see lib/citations.py).
    page_index = cite.build_page_index(years)
    cite_hits = cite_total = 0

    # Write one JSON file per pairing
    exported = 0
    for from_year in prior_years:
        analysis = database.get_change_analysis(from_year, latest)
        if analysis is None:
            print(f"  WARNING: No analysis found for {from_year}→{latest}. Run analyze_changes.py.")
            continue

        fresh = {
            "from_year": from_year,
            "to_year": latest,
            "overview": analysis["overview"],
            "sections": analysis["sections"],
        }

        filename = f"changes_{from_year}_to_{latest}.json"
        path = WEB_DATA_DIR / filename

        # 1. Capture any manual edits sitting in the file before we overwrite it.
        ondisk = _read_existing(path)
        captured = ov.capture(
            from_year, fresh, ondisk, baseline.get(str(from_year)), overrides
        )
        if captured:
            print(f"  ↳ captured manual edits in {filename}:")
            for line in captured:
                print(f"      {line}")

        # 2. Apply all stored overrides on top of the fresh DB data.
        merged = ov.apply(from_year, fresh, overrides)

        # 2b. Derive a page-level PDF citation for every quoted bullet. This is a
        #     purely computed field (`citations`), ignored by override capture.
        for section in merged["sections"]:
            cite_hits += cite.enrich(section, page_index)
            cite_total += len(section.get("bullets") or [])

        path.write_text(json.dumps(merged, indent=2, ensure_ascii=False))

        # 3. Remember what we wrote so future manual edits can be detected.
        baseline[str(from_year)] = merged

        n_sections = len(merged["sections"])
        n_overrides = len(overrides["pairs"].get(str(from_year), {}).get("changes", {}))
        note = f"  ({n_sections} sections"
        note += f", {n_overrides} manual override(s)" if n_overrides else ""
        note += ")"
        print(f"  ✓ {filename}{note}")
        exported += 1

    ov.save_overrides(overrides)
    ov.save_baseline(baseline)

    if cite_total:
        print(f"\n✓ Page citations matched {cite_hits}/{cite_total} quotes "
              f"({100 * cite_hits // cite_total}%)")

    print(f"\n✓ Exported {exported} change files + manifest to {WEB_DATA_DIR}")
    print(f"✓ Manual overrides stored in {ov.OVERRIDES_PATH.relative_to(PROJECT_ROOT)} "
          f"(edits here are permanent)")


if __name__ == "__main__":
    export_all()

"""
Token-free backfill: tag every existing change with the 2026 chapter it came from,
so the frontend can group changes by chapter and build a table of contents.

This does NOT call any LLM. It re-uses the same quote-containment matching as the
analysis step: each change's bullets are verbatim 2026 quotes, so we locate the
2026 section (and thus chapter) whose body contains the quote.

Run this once after upgrading the chapter-grouping feature. New analyses produced by
analyze_changes.py already include the chapter fields, so this is only for data that
was generated before the feature existed.

Usage:
    python3 scripts/backfill_chapters.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database
from analyze_changes import _inject_chapter_and_images


def backfill() -> None:
    years = database.get_all_manual_years()
    if len(years) < 2:
        print("Need at least 2 years in DB.")
        sys.exit(1)

    latest = years[-1]
    new_sections = database.get_sections_for_year(latest)

    updated = 0
    for from_year in years[:-1]:
        analysis = database.get_change_analysis(from_year, latest)
        if analysis is None:
            continue

        changes = analysis["sections"]
        for ch in changes:
            if ch.get("change_type") == "removed":
                ch["chapter"] = "No Longer Included"
                ch["chapter_num"] = 99
                continue
            # Clear stale fallbacks so injection can re-resolve
            ch.pop("chapter", None)
            ch.pop("chapter_num", None)
            _inject_chapter_and_images(ch, new_sections)

        database.upsert_change_analysis(
            from_year=from_year,
            to_year=latest,
            overview_text=analysis["overview"],
            sections=changes,
        )

        import collections
        dist = collections.Counter(c.get("chapter") for c in changes)
        print(f"  [{from_year}→{latest}] {len(changes)} changes tagged: {dict(dist)}")
        updated += 1

    print(f"\n✓ Backfilled {updated} analyses. Run export_json.py to refresh web/data/.")


if __name__ == "__main__":
    backfill()

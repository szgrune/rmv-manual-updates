"""
Semantic change analysis for Driver's Manual editions.

Strategy (full-context approach):
  1. Assemble the COMPLETE old manual text in reading order.
  2. Split the 2026 manual into chunks of ~25k chars (to keep API calls manageable).
  3. For each 2026 chunk, send it to the LLM alongside the COMPLETE old manual text.
     The LLM can search the entire old manual for matching content, so reorganized
     sections are found correctly regardless of chapter.
  4. The LLM reports only genuine changes with direct verbatim quotes from 2026.
  5. A final removal-detection pass finds content present in old but absent from 2026.

This eliminates false positives from:
  - Failed chapter matching (e.g. 2023 missing chapter 3 in extraction)
  - Section-level extraction artifacts (split sections, noise headings)
  - Content reorganized between chapters or pages

Multiple runs + merge: the analysis is non-deterministic, so each pair can be analyzed
several times and the canonical result is the MERGE of all runs (lib/merge.py), keyed
so the earliest occurrence of a change keeps its id (overrides stay valid across runs).

Usage:
    python3 scripts/analyze_changes.py            # analyze pairs not yet analyzed (1 run each)
    python3 scripts/analyze_changes.py --runs 3   # append 3 runs per pair, re-merge (more coverage)
    python3 scripts/analyze_changes.py --reset     # discard prior runs and redo from scratch
    ANALYZER_BACKEND=openai python3 scripts/analyze_changes.py
"""

import re
import sys
import time
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database
from lib import merge
from lib.llm_client import get_analyzer

# ── Tuning ────────────────────────────────────────────────────────────────────

CHUNK_SIZE = 25_000   # chars of 2026 text per API call (~6-7k tokens)
SLEEP_SECS = 2        # pause between API calls


# ── Text assembly ─────────────────────────────────────────────────────────────

def _assemble_text(sections: list[dict]) -> str:
    """
    Join all sections in reading order (chapter, page).
    Includes section headings so Claude can orient itself.
    """
    ordered = sorted(sections, key=lambda s: (s["chapter_num"], s["page"], s["id"]))
    parts = []
    prev_ch = None
    for sec in ordered:
        if sec["chapter_num"] != prev_ch:
            parts.append(f"\n══ {sec['chapter_title']} ══\n")
            prev_ch = sec["chapter_num"]
        parts.append(f"[{sec['title']}]\n{sec['body_text']}")
    return "\n\n".join(parts)


def _split_into_chunks(text: str, chunk_size: int) -> list[str]:
    """
    Split text into chunks of at most chunk_size chars, breaking only at section
    boundaries (lines starting with '[') to avoid mid-section cuts.
    """
    chunks = []
    current_parts = []
    current_len = 0

    for line in text.split("\n\n"):
        if current_len + len(line) > chunk_size and current_parts:
            chunks.append("\n\n".join(current_parts))
            current_parts = []
            current_len = 0
        current_parts.append(line)
        current_len += len(line) + 2  # +2 for the separator

    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks


# ── Helpers ───────────────────────────────────────────────────────────────────

def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text)


def _strip_chapter_prefix(title: str) -> str:
    """Drop a leading 'Chapter N' so headings read e.g. 'Safety First'."""
    return re.sub(r"^\s*chapter\s+\d+\s*[:.\-–]?\s*", "", title, flags=re.I).strip()


def _quote_text(bullet: str) -> str:
    """Extract the quoted text from a bullet like '"..." (2026 ... Manual)'."""
    m = re.search(r'"([^"]+)"', bullet)
    return m.group(1) if m else bullet


def _find_source_section(change: dict, new_sections: list[dict]):
    """
    Locate the 2026 section a change came from. Primary strategy: the bullets are
    verbatim quotes from 2026, so find the section whose body contains the quote.
    Fallback: fuzzy title match. Returns (section, score) or (None, 0.0).
    """
    # 1. Quote containment — exact and reliable
    for bullet in change.get("bullets", []):
        q = re.sub(r"\s+", " ", _quote_text(bullet).strip().lower())
        if len(q) < 12:
            continue
        probe = q[:60]
        for sec in new_sections:
            body = re.sub(r"\s+", " ", sec["body_text"].lower())
            if probe in body:
                return sec, 1.0

    # 2. Fuzzy title match — fallback
    import difflib
    best_ratio, best_sec = 0.0, None
    change_title = change.get("title", "").lower()
    for sec in new_sections:
        ratio = difflib.SequenceMatcher(None, change_title, sec["title"].lower()).ratio()
        if ratio > best_ratio:
            best_ratio, best_sec = ratio, sec
    return best_sec, best_ratio


def _inject_chapter_and_images(
    change: dict, new_sections: list[dict], other_chapter_label: str = "Other Updates"
) -> None:
    """Tag a change with its source chapter (for TOC grouping) and attach images."""
    sec, score = _find_source_section(change, new_sections)
    if sec and score >= 0.30:
        change.setdefault("chapter", _strip_chapter_prefix(sec["chapter_title"]))
        change.setdefault("chapter_num", sec["chapter_num"])
        if not change.get("images") and score >= 0.45 and sec.get("images"):
            change["images"] = sec["images"]
    # Fallbacks for anything we couldn't place
    change.setdefault("chapter", other_chapter_label)
    change.setdefault("chapter_num", 98)


# ── Removal detection ─────────────────────────────────────────────────────────

def _removal_candidates(old_sections: list[dict], new_full_text: str) -> list[dict]:
    """
    Return old sections whose content is NOT well-represented in the 2026 full text,
    i.e. candidates for having been removed.
    """
    new_words = set(re.findall(r"\b[a-z]{5,}\b", new_full_text.lower()))
    candidates = []
    for sec in old_sections:
        title = sec["title"].strip()
        body  = sec["body_text"].strip()
        if len(body) < 200 or len(title) < 5 or not title[0].isupper():
            continue
        # Exclude obvious noise titles
        if re.search(r"\d{3}[-.]?\d{3}[-.]?\d{4}|@|/", title):
            continue
        if title.endswith(".") and len(title.split()) >= 3:
            continue
        # Word overlap: if most significant words still appear in 2026, it's probably present
        old_words = set(re.findall(r"\b[a-z]{5,}\b", body.lower()))
        if not old_words:
            continue
        overlap = len(old_words & new_words) / len(old_words)
        if overlap < 0.55:   # less than 55% of words found → candidate for removal
            candidates.append(sec)
    return candidates


# ── Main analysis per year pair ───────────────────────────────────────────────

def _run_single_analysis(
    old_year, new_year, analyzer, old_sections, new_sections,
    old_full_text, new_full_text, language, inclusive,
    other_chapter_label, removed_chapter_label,
) -> list[dict]:
    """One full analysis pass (chunk comparison + removal detection). Returns the raw
    change list; does NOT generate an overview or write to the DB."""
    new_chunks = _split_into_chunks(new_full_text, CHUNK_SIZE)
    print(f"  {new_year} split into {len(new_chunks)} chunks")

    all_changes: list[dict] = []
    for i, chunk in enumerate(new_chunks, 1):
        print(f"\n  Chunk {i}/{len(new_chunks)} ({len(chunk):,} chars)...", end=" ", flush=True)
        result = analyzer.compare_chapters(
            chapter_title=f"Chunk {i} of {len(new_chunks)}",
            old_year=old_year,
            old_text=old_full_text,
            new_year=new_year,
            new_text=chunk,
            language=language,
            inclusive=inclusive,
        )
        changes = result.get("changes", [])
        for ch in changes:
            ch.setdefault("id", _slugify(ch.get("title", "change")))
            ch.setdefault("images", [])
            _inject_chapter_and_images(ch, new_sections, other_chapter_label)
            all_changes.append(ch)
        print(f"{len(changes)} changes found")
        if i < len(new_chunks):
            time.sleep(SLEEP_SECS)

    # ── Removal detection pass ────────────────────────────────────────────────
    existing_slugs = {_slugify(c.get("title", "")) for c in all_changes}
    candidates = _removal_candidates(old_sections, new_full_text)
    candidates = [c for c in candidates if _slugify(c["title"]) not in existing_slugs]
    if candidates:
        print(f"\n  Checking {len(candidates)} removal candidates...", end=" ", flush=True)
        time.sleep(SLEEP_SECS)
        removed = analyzer.find_removed_content(
            candidates, new_full_text, old_year, new_year=new_year, language=language
        )
        for item in removed:
            all_changes.append({
                "id":          _slugify(item.get("title", "removed")),
                "title":       item.get("title", ""),
                "change_type": "removed",
                "description": item.get("description", ""),
                "bullets":     item.get("bullets", []),
                "images":      [],
                "chapter":     removed_chapter_label,
                "chapter_num": 99,
            })
        print(f"{len(removed)} confirmed removed")
        time.sleep(SLEEP_SECS)

    return all_changes


def remerge_pair(old_year, new_year, analyzer=None, language="English") -> list[dict] | None:
    """
    Re-merge every stored run for a pair into the canonical change_analyses row.
    If `analyzer` is given the overview is regenerated from the merged set; otherwise
    the existing overview is kept (so this can run API-free, e.g. after editing runs).
    """
    runs = database.get_analysis_runs(old_year, new_year)
    if not runs:
        print(f"  [{old_year}→{new_year}] No stored runs to merge.")
        return None

    merged = merge.merge_change_sets(runs)
    if analyzer is not None:
        print(f"  Generating overview ({len(merged)} merged changes)...", end=" ", flush=True)
        overview = analyzer.generate_overview(
            merged, old_year, new_year=new_year, language=language
        )
        print("done")
    else:
        existing = database.get_change_analysis(old_year, new_year)
        overview = existing["overview"] if existing else ""

    database.upsert_change_analysis(old_year, new_year, overview, merged)
    print(f"  ✓ [{old_year}→{new_year}] Merged {len(runs)} run(s) → {len(merged)} unique changes")
    return merged


def analyze_pair(
    old_year: int,
    new_year: int,
    analyzer,
    runs: int = 1,
    reset: bool = False,
    force: bool | None = None,
    language: str = "English",
    other_chapter_label: str = "Other Updates",
    removed_chapter_label: str = "No Longer Included",
    inclusive: bool = False,
) -> None:
    """
    Run the analysis `runs` time(s), append each run, and re-merge all stored runs
    into the canonical analysis. Coverage accumulates across invocations unless
    `reset=True` (clears prior runs first). `force` is a back-compat alias for reset.
    """
    if force is not None:
        reset = reset or bool(force)

    print(f"\n{'='*60}")
    print(f"Analyzing {old_year} → {new_year}  (runs={runs}, reset={reset})")
    print(f"{'='*60}")

    if reset:
        database.clear_analysis_runs(old_year, new_year)
        print(f"  Reset: cleared stored runs for {old_year}→{new_year}")

    # Auto-migrate a legacy single analysis (pre-multi-run) into run 1 so existing
    # coverage and override ids are preserved.
    if database.count_analysis_runs(old_year, new_year) == 0:
        existing = database.get_change_analysis(old_year, new_year)
        if existing and existing.get("sections"):
            database.insert_analysis_run(old_year, new_year, existing["sections"])
            print(f"  Migrated existing analysis into run 1 ({len(existing['sections'])} changes)")

    old_sections = database.get_sections_for_year(old_year)
    new_sections = database.get_sections_for_year(new_year)
    if not old_sections or not new_sections:
        print("  ERROR: Missing sections. Run extract first.")
        return

    old_full_text = _assemble_text(old_sections)
    new_full_text = _assemble_text(new_sections)
    print(f"  Old manual: {len(old_full_text):,} chars  |  New manual: {len(new_full_text):,} chars")

    for r in range(1, runs + 1):
        print(f"\n  ─── Analysis run {r}/{runs} ───")
        changes = _run_single_analysis(
            old_year, new_year, analyzer, old_sections, new_sections,
            old_full_text, new_full_text, language, inclusive,
            other_chapter_label, removed_chapter_label,
        )
        database.insert_analysis_run(old_year, new_year, changes)
        print(f"  Run {r} stored: {len(changes)} raw changes")

    remerge_pair(old_year, new_year, analyzer=analyzer, language=language)
    total = database.count_analysis_runs(old_year, new_year)
    print(f"\n✓ [{old_year}→{new_year}] Complete — {total} run(s) accumulated")


# ── Entry point ───────────────────────────────────────────────────────────────

def _arg_int(flag: str, default: int) -> tuple[int, bool]:
    """Return (value, was_given) for `--flag N`."""
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            try:
                return int(sys.argv[i + 1]), True
            except ValueError:
                pass
    return default, False


def main():
    reset = ("--reset" in sys.argv) or ("--force" in sys.argv)
    runs, runs_given = _arg_int("--runs", 1)

    years = database.get_all_manual_years()
    if len(years) < 2:
        print("Need at least 2 years in DB. Run extract_pdfs.py first.")
        sys.exit(1)

    latest      = years[-1]
    prior_years = years[:-1]

    print(f"Latest year: {latest}")
    print(f"Pairs to analyze: {[f'{y}→{latest}' for y in prior_years]}")

    analyzer = get_analyzer()
    print(f"Analyzer backend: {type(analyzer).__name__}\n")

    for old_year in prior_years:
        # Preserve the cheap default: a bare run skips pairs already analyzed.
        # --runs N appends coverage; --reset/--force redoes from scratch.
        already = (
            database.count_analysis_runs(old_year, latest) > 0
            or database.get_change_analysis(old_year, latest) is not None
        )
        if already and not reset and not runs_given:
            print(f"  [{old_year}→{latest}] Already analyzed — skipping "
                  f"(use --runs N to add coverage, or --reset to redo)")
            continue
        analyze_pair(old_year, latest, analyzer, runs=runs, reset=reset)

    print("\n\n✓ All analyses complete.")


if __name__ == "__main__":
    main()

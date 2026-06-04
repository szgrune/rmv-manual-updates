"""
Manual-edit overrides layer.

The AI pipeline (analyze_changes.py) writes change analyses into SQLite, and
export_json.py regenerates web/data/changes_*.json from that DB. Without this
layer, any hand-edit to those JSON files is lost on the next export.

This module makes manual edits PERMANENT. It works in two phases, both driven
from export_json.py:

  capture()  Before a file is overwritten, compare what's on disk against a
             stored baseline (the content we last wrote). Anything that differs
             is a manual edit, and it gets folded into data/overrides.json.

  apply()    After regenerating fresh data from the DB, overlay the stored
             overrides so manual edits always win over AI output.

Overrides are keyed by from_year and by each change's stable `id` (the slug of
its title). They are deliberately NOT keyed by to_year, so a correction to the
"2023 → latest" comparison keeps applying after you add a newer manual and the
comparison target changes (e.g. 2026 → 2028).

You can also edit data/overrides.json by hand; entries there are authoritative.
"""

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
OVERRIDES_PATH = PROJECT_ROOT / "data" / "overrides.json"
BASELINE_PATH = PROJECT_ROOT / "data" / ".export_baseline.json"

# Fields that make up a change object. `id` is the identity key and is never
# itself overridden.
_CHANGE_FIELDS = (
    "title", "change_type", "description", "bullets",
    "images", "chapter", "chapter_num",
)

_README = (
    "Manual corrections to the AI-generated change data. These edits are "
    "PERMANENT and always win over AI output — they are re-applied every time "
    "export_json.py runs, including after re-analyzing new PDFs. Entries are "
    "captured automatically from edits you make to web/data/changes_*.json, but "
    "you may also edit this file by hand. Keyed by from_year, then by each "
    "change's stable `id`. action: edit | delete | add."
)


# ── Persistence ────────────────────────────────────────────────────────────────

def load_overrides() -> dict:
    if OVERRIDES_PATH.exists():
        try:
            data = json.loads(OVERRIDES_PATH.read_text())
            data.setdefault("pairs", {})
            return data
        except json.JSONDecodeError:
            print(f"  WARNING: {OVERRIDES_PATH.name} is not valid JSON — ignoring it. "
                  f"Fix the file to restore your overrides.")
    return {"_README": _README, "version": 1, "pairs": {}}


def save_overrides(overrides: dict) -> None:
    overrides["_README"] = _README
    overrides.setdefault("version", 1)
    OVERRIDES_PATH.write_text(json.dumps(overrides, indent=2, ensure_ascii=False))


def load_baseline() -> dict:
    if BASELINE_PATH.exists():
        try:
            return json.loads(BASELINE_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def save_baseline(baseline: dict) -> None:
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2, ensure_ascii=False))


# ── Capture: detect manual edits on disk ────────────────────────────────────────

def capture(from_year: int, fresh: dict, ondisk: dict | None,
            baseline: dict | None, overrides: dict) -> list[str]:
    """
    Compare the on-disk JSON file against a baseline and record any manual edits
    into `overrides` (mutated in place). Returns a human-readable summary list.

    The baseline is the content we last wrote for this from_year. On the very
    first run (no baseline yet) we fall back to comparing against `fresh` (raw AI
    output), so pre-existing hand-edits are adopted rather than lost.
    """
    if ondisk is None:
        return []
    base = baseline if baseline is not None else fresh

    summary: list[str] = []
    pair = overrides["pairs"].setdefault(str(from_year), {})
    ov_changes = pair.setdefault("changes", {})

    # Overview
    if ondisk.get("overview") != base.get("overview"):
        pair["overview"] = ondisk.get("overview", "")
        summary.append("overview")

    base_by_id = {c.get("id"): c for c in base.get("sections", []) if c.get("id")}
    disk_by_id = {c.get("id"): c for c in ondisk.get("sections", []) if c.get("id")}

    # Edits and user-added changes
    for cid, dch in disk_by_id.items():
        bch = base_by_id.get(cid)
        if bch is None:
            # Present on disk but never written by us → a hand-added change.
            ov_changes[cid] = {
                "action": "add",
                "fields": {k: dch[k] for k in dch if k != "id"},
            }
            summary.append(f"+ added '{cid}'")
            continue

        diff = {}
        for key in (set(dch) | set(bch)):
            if key == "id":
                continue
            if dch.get(key) != bch.get(key):
                diff[key] = dch.get(key)
        if diff:
            existing = ov_changes.get(cid)
            if existing and existing.get("action") == "add":
                existing.setdefault("fields", {}).update(diff)
            else:
                entry = ov_changes.setdefault(cid, {"action": "edit", "fields": {}})
                entry["action"] = "edit"
                entry.setdefault("fields", {}).update(diff)
            summary.append(f"~ edited '{cid}' ({', '.join(sorted(diff))})")

    # Deletions: present in baseline but removed from the on-disk file
    for cid in base_by_id:
        if cid not in disk_by_id:
            ov_changes[cid] = {"action": "delete"}
            summary.append(f"- deleted '{cid}'")

    return summary


# ── Apply: overlay overrides onto freshly generated data ─────────────────────────

def apply(from_year: int, fresh: dict, overrides: dict) -> dict:
    """
    Return a copy of `fresh` (DB-derived) with all stored overrides for this
    from_year applied: field-level edits, deletions, and hand-added changes.
    """
    pair = overrides.get("pairs", {}).get(str(from_year), {})
    ov_changes = pair.get("changes", {})

    overview = fresh.get("overview", "")
    if pair.get("overview") is not None:
        overview = pair["overview"]

    out_changes: list[dict] = []
    seen: set[str] = set()

    for ch in fresh.get("sections", []):
        cid = ch.get("id")
        seen.add(cid)
        o = ov_changes.get(cid)
        if not o:
            out_changes.append(ch)
            continue
        action = o.get("action")
        if action == "delete":
            continue
        # edit / add → merge overridden fields on top of the fresh change
        out_changes.append({**ch, **o.get("fields", {})})

    # Hand-added changes that the AI doesn't produce
    for cid, o in ov_changes.items():
        if cid in seen:
            continue
        if o.get("action") == "add":
            out_changes.append({"id": cid, **o.get("fields", {})})
        # 'edit'/'delete' overrides for ids no longer produced by the AI are
        # kept in the store (harmless) but have nothing to apply to.

    return {
        "from_year": fresh.get("from_year", from_year),
        "to_year": fresh.get("to_year"),
        "overview": overview,
        "sections": out_changes,
    }

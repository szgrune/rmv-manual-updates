# Driver's Manual Updates Web App — Implementation Plan

## Context

Build a static, iframe-embeddable web app that compares Massachusetts Driver's Manual editions (2007, 2017, 2023, 2026) and shows users what driving laws changed since they got their license.

**Deployment constraint (critical):** The target organization has no access to Claude Code or the Claude API. They hold an enterprise OpenAI account but will not allocate tokens to this app. The prototype may use the Claude API for development, but the architecture must be designed so the LLM provider can be swapped to OpenAI (or a fully token-free local approach) without structural changes to the codebase.

**Scalability requirement:** When a new Driver's Manual is added to the Manuals folder, the system must automatically re-analyze all pairings involving the new year and persist the results to a backend database. The frontend always reads pre-computed data — it never performs analysis at user request time.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  BUILD PIPELINE (runs once + on each new manual upload) │
│                                                         │
│  Manuals/*.pdf ──► PDF Extractor ──► SQLite DB          │
│                                         │               │
│                    LLM Analyzer ◄───────┘               │
│                    (Claude / OpenAI / Local)             │
│                         │                               │
│                    SQLite DB ──► JSON Exporter          │
└─────────────────────────────────────────────────────────┘
                               │
                          web/data/*.json
                               │
┌──────────────────────────────▼──────────────────────────┐
│  FRONTEND (fully static, iframe-embeddable)             │
│                                                         │
│  index.html + styles.css + app.js                       │
│  fetch() ──► pre-generated JSON files                   │
└─────────────────────────────────────────────────────────┘
```

The frontend is always fully static. The database is the canonical backend store; JSON files are exports from it that the frontend consumes. No runtime API calls happen in the browser.

---

## Directory Structure

```
RMV Quiz Project/
├── Manuals/                          (source PDFs — add new years here)
│   ├── Drivers_Manual_2007.pdf
│   ├── Drivers_Manual_2017.pdf
│   ├── Drivers_Manual_2023.pdf
│   └── Drivers_Manual_2026.pdf
│
├── scripts/
│   ├── requirements.txt
│   ├── extract_pdfs.py               (extract text + images from all PDFs)
│   ├── analyze_changes.py            (run LLM/local analysis, write to DB)
│   ├── export_json.py                (read DB → write web/data/*.json)
│   ├── update_manual.py              (entry point for adding a new manual year)
│   └── lib/
│       ├── __init__.py
│       ├── pdf_extractor.py          (pymupdf extraction logic)
│       ├── image_associator.py       (map images to sections by page proximity)
│       ├── llm_client.py             (abstract base + provider implementations)
│       └── db.py                     (SQLite schema + read/write helpers)
│
├── data/
│   └── manuals.db                    (SQLite — canonical backend store)
│
├── web/
│   ├── index.html
│   ├── styles.css
│   ├── app.js
│   ├── data/
│   │   ├── manifest.json             (list of available years — auto-generated)
│   │   ├── changes_2007_to_2026.json
│   │   ├── changes_2017_to_2026.json
│   │   └── changes_2023_to_2026.json
│   └── images/
│       ├── 2026/   (p088_img0.png, ...)
│       ├── 2023/
│       ├── 2017/
│       └── 2007/
│
├── build.sh                          (full clean build)
└── PLAN.md                           (this file)
```

---

## Phase 1A: PDF Extraction (`scripts/lib/pdf_extractor.py`)

**Libraries:** `pymupdf` (fitz) for all extraction — zero API tokens. `Pillow` for image format normalization (CMYK → PNG, etc.).

**Logic:**
1. Detect chapter boundaries: scan pages for spans with font size > 14 matching `CHAPTER \d+`.
2. Detect section headings within chapters: bold spans forming a complete short line (< 60 chars, title-cased or all-caps).
3. Accumulate text blocks under each section; normalize whitespace and bullet characters.
4. Extract images: `page.get_images(full=True)`, filter to width > 80 px, height > 80 px, aspect ratio not extreme (skip decorative column rules). Save as `web/images/[year]/p[NNN]_img[N].png`.
5. Associate images to sections by page proximity: image belongs to the section whose heading most recently preceded it.

**Failure mitigations:**
- `extract_image(xref)` fails for unusual formats (JBIG2/JPX): fall back to `page.get_pixmap(clip=bbox)` rasterization.
- Print section count per year; if < 20, threshold needs tuning.

---

## Phase 1B: SQLite Backend (`scripts/lib/db.py`)

SQLite is used as the canonical backend store for all extracted content and pre-computed analyses. It is the single source of truth; JSON files are always derived from it.

**Schema:**

```sql
-- One row per manual year
CREATE TABLE manuals (
    year        INTEGER PRIMARY KEY,
    added_at    TEXT NOT NULL
);

-- One row per extracted section
CREATE TABLE sections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    year        INTEGER NOT NULL REFERENCES manuals(year),
    chapter_num INTEGER NOT NULL,
    chapter_title TEXT NOT NULL,
    section_key TEXT NOT NULL,   -- kebab-case unique id
    title       TEXT NOT NULL,
    page        INTEGER NOT NULL,
    body_text   TEXT NOT NULL
);

-- One row per image, linked to a section
CREATE TABLE images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section_id  INTEGER NOT NULL REFERENCES sections(id),
    src_path    TEXT NOT NULL,   -- relative to web/, e.g. images/2026/p012_img0.png
    alt_text    TEXT NOT NULL DEFAULT '',
    caption     TEXT NOT NULL DEFAULT ''
);

-- One row per pre-computed change pairing
CREATE TABLE change_analyses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    from_year       INTEGER NOT NULL,
    to_year         INTEGER NOT NULL,
    computed_at     TEXT NOT NULL,
    overview_text   TEXT NOT NULL,
    sections_json   TEXT NOT NULL,  -- JSON blob: array of change section objects
    UNIQUE(from_year, to_year)
);
```

`db.py` exposes helpers: `insert_manual()`, `insert_section()`, `insert_image()`, `upsert_change_analysis()`, `get_change_analysis(from_year, to_year)`, `get_all_manual_years()`.

---

## Phase 1C: LLM Analyzer — Provider-Agnostic Layer (`scripts/lib/llm_client.py`)

This is the key abstraction layer. All three provider implementations share the same interface so the caller (`analyze_changes.py`) never needs to know which backend is active.

**Configuration:** Set via environment variable `ANALYZER_BACKEND=claude|openai|local`. The default is `claude` for the prototype.

**Abstract base class:**

```python
class LLMAnalyzer:
    def analyze_chapter(
        self,
        chapter_title: str,
        old_year: int,
        old_text: str,
        new_year: int,
        new_text: str,
    ) -> dict:
        """
        Returns a dict matching the change section schema:
        {
          "chapter": str,
          "chapter_overview": str,
          "sections": [
            { "id": str, "title": str, "change_type": str,
              "description": str, "bullets": [str], "images": [] }
          ]
        }
        """
        raise NotImplementedError
```

**Three implementations:**

### 1. `ClaudeAnalyzer` (prototype — current)
- Uses `anthropic` SDK, `claude-sonnet-4-6`
- Prompt caching on the 2026 chapter text (stable across all comparison pairs)
- Retry loop (max 3) on JSON parse failure, feeding the error back to Claude
- 2-second sleep between calls

### 2. `OpenAIAnalyzer` (for org's enterprise account — future swap)
- Uses `openai` SDK, `gpt-4o` or `gpt-4-turbo`
- Identical prompt structure; only the SDK call changes
- Uses `response_format={"type": "json_object"}` for reliable JSON output
- Swappable by changing `ANALYZER_BACKEND=openai` and setting `OPENAI_API_KEY`

### 3. `LocalAnalyzer` (fully token-free fallback)
- No API calls whatsoever
- Uses `sentence-transformers` (local model: `all-MiniLM-L6-v2`, ~80 MB) for semantic section matching
- Uses `difflib.unified_diff` + custom heuristics to identify changed prose
- Regex patterns to extract structured changes: fines (`\$\d+`), speed limits, dates, law names
- Lower accuracy than LLM analysis but zero marginal cost; usable for bulk re-analysis when API budget is constrained
- Surfaced as `ANALYZER_BACKEND=local`

**Switching between providers requires only:**
```bash
ANALYZER_BACKEND=openai OPENAI_API_KEY=... python3 scripts/analyze_changes.py
```
No code changes needed.

**`requirements.txt` is split by backend:**

```
# requirements.txt (always required)
pymupdf>=1.24.0
Pillow>=10.0.0

# requirements-claude.txt (prototype)
anthropic>=0.30.0

# requirements-openai.txt (org production)
openai>=1.30.0

# requirements-local.txt (token-free fallback)
sentence-transformers>=2.7.0
torch>=2.0.0  # CPU-only install is sufficient
```

---

## Phase 1D: Change Analysis (`scripts/analyze_changes.py`)

**Chapter alignment across editions:** Map chapters by title similarity (`difflib.SequenceMatcher`, ratio > 0.6), not by chapter number. The 2023/2026 editions reorganized from 6 chapters to 5.

**Chunking unit:** One chapter at a time per comparison pair. ~5 chapters × N pairs = manageable API calls.

**System prompt (shared across Claude and OpenAI):**
> You are an expert analyst of Massachusetts driver's manual editions. Compare an older edition chapter to the 2026 edition chapter and identify only genuine legal/regulatory changes, new laws, updated fines/penalties, new road behaviors, and newly-added sections. Exclude paragraph restructuring, minor wording changes that don't alter meaning, and formatting differences. Output only valid JSON.

**Per-chapter JSON schema requested:**
```json
{
  "chapter": "Safety First",
  "chapter_overview": "2-3 sentence summary of most important changes.",
  "sections": [
    {
      "id": "hands-free-law",
      "title": "Hands-Free Law",
      "change_type": "new",
      "description": "One-sentence explanation of change.",
      "bullets": ["Specific factual statement...", "..."],
      "images": []
    }
  ]
}
```
`change_type` values: `"new"` | `"updated"` | `"expanded"` | `"removed"`

**Post-processing:** After LLM returns section JSON, fuzzy-match section titles against extracted 2026 sections in the DB and inject the matching section's image references into the `"images"` array.

**Write to DB:** Call `db.upsert_change_analysis(from_year, to_year, overview, sections_json)` after each pair is complete.

**Ground-truth cross-check:** `Drivers_Manual_New_Topics.md` documents known major new topics (Hands-Free Law, Move-Over Law, Vulnerable Road Users, ADAS, etc.). Inspect output JSON against this list after generation.

---

## Phase 1E: JSON Export (`scripts/export_json.py`)

Reads all `change_analyses` rows from SQLite and writes one JSON file per pairing to `web/data/`. Also writes `web/data/manifest.json` with the list of all available manual years and the latest year. This step is always run after analysis and after any manual update.

**`manifest.json` schema:**
```json
{
  "manual_years": [2007, 2017, 2023, 2026],
  "latest_year": 2026
}
```

**Change file schema** (what the frontend consumes):
```json
{
  "from_year": 2007,
  "to_year": 2026,
  "overview": "Combined chapter overview paragraph...",
  "sections": [
    {
      "id": "hands-free-law",
      "title": "Hands-Free Law",
      "change_type": "new",
      "description": "...",
      "bullets": ["..."],
      "images": [{ "src": "images/2026/p047_img0.png", "alt": "...", "caption": "" }]
    }
  ]
}
```

---

## Phase 1F: New Manual Update Flow (`scripts/update_manual.py`)

This is the entry point for adding future manual years (e.g., `Drivers_Manual_2028.pdf`).

**Usage:**
```bash
python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf
```

**What it does:**
1. Checks if the year (parsed from filename) already exists in the DB; exits with a clear message if so.
2. Runs `pdf_extractor.py` logic on the new file, saves sections + images to DB.
3. Determines the new "latest year" and all prior years in the DB.
4. Runs change analysis for every pairing `[prior_year] → [new_year]`.
5. Writes all new analyses to the DB via `upsert_change_analysis`.
6. Calls `export_json.py` to regenerate all JSON files in `web/data/`.
7. Prints a summary: how many new analyses were computed, which JSON files were updated.

**No manual intervention needed after the initial setup.** Adding a new PDF and running this script is the entire update workflow.

---

## Phase 2: Frontend

### Design Tokens (CSS custom properties)
```css
:root {
  --color-brand: #14558F;
  --color-bg: #ffffff;
  --color-body: #000000;
  --color-accent-light: #e8f0f8;
  --color-border: #d0dce8;
  --font-heading: 'Poppins', sans-serif;    /* weights 600, 700 */
  --font-body: 'IBM Plex Sans', sans-serif; /* weights 400, 500 */
  --radius: 6px;
  --max-width: 860px;
}
```

### `index.html` Structure
- `<h1>` "Driver's Manual Updates by Year" (Poppins, brand color)
- Year selector row: `<label>` "Select the year you got your driver's license:", `<select id="year-select">` (options populated dynamically from `manifest.json`)
- `"2026 Updates"` accordion: full-width toggle button with animated chevron; body **collapsed by default**; **always visible, never hidden by year selection**
- `"Changes since [year]"` section: **appears below the accordion** (both coexist); hidden until user selects a year; contains overview callout block + section cards organized **flat by topic** (not grouped by era)
- No year-note / mapping notice needed — the dropdown only presents exact manual years, eliminating ambiguity

### Year Dropdown Population (`app.js`)
On page load, fetch `data/manifest.json` and use it to build the `<select>` options. The `<select>` includes a disabled default option ("Select a year...") and one `<option>` per year listed in ascending order. Selecting a year immediately triggers data load and render — no separate submit button needed. Adding a new manual and re-running the build pipeline automatically adds it to the dropdown.

### Data Loading (`app.js`)
- On load: fetch `data/manifest.json` → populate dropdown; fetch `data/changes_[secondLatest]_to_[latest].json` → populate accordion (cached)
- On year select: fetch `data/changes_[selectedYear]_to_[latestYear].json` lazily, cache all loaded files in a module-level object
- If the user selects the latest year (e.g., 2026), show: "You selected the most current manual year. No changes to display."

### Rendering
- **Accordion body:** all sections from `changes_[secondLatest]_to_[latest].json` as cards
- **Changes section:** `<h2>` heading + overview callout box + section cards list
- **Section card:** Poppins bold title + change-type badge pill + description `<p>` + `<ul>` bullets + `<figure><img loading="lazy"><figcaption>` per image
- **Change-type badges:** colored pills — new=green, updated=amber, expanded=blue, removed=red
- **Accordion animation:** `max-height` CSS transition; chevron rotates 180° on expand

### Edge Cases
- Latest year selected: show "You selected the most current manual year. No changes to display."
- `manifest.json` fetch fails: show fallback error state with guidance to reload.
- Change data fetch fails: "Could not load update data. Please try again."
- Loading state: disable dropdown and show "Loading..." while fetching.

---

## Phase 3: Build Orchestration

### `build.sh` (full clean build)
```bash
#!/usr/bin/env bash
set -euo pipefail
echo "=== Installing dependencies ==="
pip install -r scripts/requirements.txt
pip install -r scripts/requirements-claude.txt    # swap for openai or local as needed

echo "=== Extracting PDFs ==="
python3 scripts/extract_pdfs.py

echo "=== Analyzing changes ==="
# ANALYZER_BACKEND defaults to "claude"; swap to "openai" or "local" via env var
python3 scripts/analyze_changes.py

echo "=== Exporting JSON ==="
python3 scripts/export_json.py

echo "=== Done. Serve with: cd web && python3 -m http.server 8080 ==="
```

### Development Server
```bash
cd web && python3 -m http.server 8080
```
Required because `fetch()` fails under `file://` due to CORS. For production, upload `web/` to any static host (GitHub Pages, Netlify, S3, etc.).

---

## LLM Provider Migration Guide (for org handoff)

When the organization is ready to switch from Claude to their OpenAI enterprise account:

1. `pip install -r scripts/requirements-openai.txt`
2. Set env vars: `ANALYZER_BACKEND=openai OPENAI_API_KEY=[key]`
3. Re-run: `python3 scripts/analyze_changes.py && python3 scripts/export_json.py`
4. No frontend or schema changes needed.

When switching to fully token-free mode:

1. `pip install -r scripts/requirements-local.txt`
2. Set: `ANALYZER_BACKEND=local`
3. Re-run analysis and export (first run downloads the ~80 MB sentence-transformers model).
4. Expect lower output quality — suitable for bulk re-analysis or environments with zero API budget.

---

## Implementation Order

1. `scripts/requirements*.txt` + install
2. `scripts/lib/db.py` — schema creation + helpers
3. `scripts/lib/pdf_extractor.py` — test on 2026 alone, verify DB rows + saved images
4. `scripts/lib/image_associator.py` — verify section→image mapping
5. `scripts/extract_pdfs.py` — run all 4 years, populate DB
6. `scripts/lib/llm_client.py` — abstract base + `ClaudeAnalyzer` first
7. `scripts/analyze_changes.py` — test one chapter (2023→2026), cross-check against `Drivers_Manual_New_Topics.md`
8. Full analysis run — all 3 pairs, review DB content
9. `scripts/export_json.py` — generate `web/data/*.json` + `manifest.json`, inspect output
10. `scripts/update_manual.py` — wire up the new-manual workflow, test with a renamed copy of an existing PDF
11. `web/index.html` + `web/styles.css` + `web/app.js` — develop with mock JSON, then connect real data
12. Test all dropdown selections; load in `<iframe>` on a test page
13. Implement `OpenAIAnalyzer` and `LocalAnalyzer` stubs in `llm_client.py` (full implementations deferred to org handoff)
14. `build.sh` — test clean full build

---

## Verification

- Confirm dropdown populates correctly from `manifest.json` with all available manual years
- Select each year in the dropdown — verify the correct change data loads and renders
- Select the latest year (2026) — verify "most current" message appears with no change cards
- Open "2026 Updates" accordion — chevron animates, sections render with images
- Inline images load with correct captions
- No JS console errors
- Load inside an `<iframe>` on a test HTML page — no frame-blocking issues
- Google Fonts load: Poppins (headings), IBM Plex Sans (body)
- Run `update_manual.py` with a test PDF — verify DB updated, JSON files and manifest regenerated
- Inspect SQLite DB directly (`sqlite3 data/manuals.db`) to confirm all expected rows exist

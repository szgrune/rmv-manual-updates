# Massachusetts Driver's Manual Updates

A web app that shows Massachusetts drivers **what has changed in the RMV Driver's
Manual since the year they got their license**. A user enters the year they were
licensed and sees a "Changes Since YEAR" page: new laws, updated fines and rules,
and expanded topics — each backed by a direct verbatim quote from the latest
manual with a deep link to the exact PDF page.

The public site is a fully static web app (HTML/CSS/JS) hosted on **GitHub Pages**.
All content is pre-computed by a local Python pipeline that compares manual
editions with an LLM; the browser only ever reads pre-generated JSON.

---

## Manuals currently in the corpus

The system compares every older edition against the newest one. Manuals live in
`Manuals/` and follow the naming convention **`Drivers_Manual_<YYYY>.pdf`**:

| Year | Role |
|------|------|
| 1999, 2002, 2003, 2004, 2005, 2006, 2007, 2017, 2023 | older editions (each gets a "Changes Since YEAR" page) |
| **2026** | newest edition (the comparison target) |

A separate Spanish corpus (2019, 2023) powers the site's Spanish toggle, built via
`scripts/build_spanish.py` into `*_spanish` data files.

The manual is organized into five chapters: *Obtaining Your License*, *Safety
First*, *Keeping Your License*, *Rules of the Road*, and *Special Driving
Situations*.

---

## How it works

```
Manuals/*.pdf ──▶ extract_pdfs.py ──▶ SQLite (data/manuals.db)
                                          │
                       analyze_changes.py │  (LLM: old edition vs. newest)
                                          ▼
                                  SQLite change_analyses
                                          │
                       export_json.py     │  (+ data/overrides.json, + PDF citations)
                                          ▼
                                  web/data/changes_<from>_to_<latest>.json
                                          │
                                          ▼
                        Static site (web/) on GitHub Pages
```

1. **Extract** — `scripts/extract_pdfs.py` pulls text + images from each PDF into
   a SQLite database (`data/manuals.db`).
2. **Analyze** — `scripts/analyze_changes.py` sends the full older manual plus
   chunks of the newest manual to an LLM, which reports genuine changes as verbatim
   quotes. Multiple runs are merged to accumulate coverage.
3. **Export** — `scripts/export_json.py` writes the per-year JSON the site reads,
   applying manual overrides and deriving a PDF page citation for every quote.
4. **Serve** — the static `web/` app fetches those JSON files and renders them.

### LLM backend (swappable)

The analyzer is pluggable via the **`ANALYZER_BACKEND`** environment variable so
the project isn't locked to one provider:

| `ANALYZER_BACKEND` | Provider / model | Notes |
|--------------------|------------------|-------|
| `claude` (default) | Anthropic `claude-opus-4-8` | uses prompt caching for speed/cost |
| `openai`           | OpenAI `gpt-4o` (override with `OPENAI_MODEL`) | for an enterprise OpenAI account |
| `local`            | offline `difflib` similarity | no API key, lower accuracy |

Set the matching API key (`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) before running
an analysis. Swapping backends requires no code changes.

### Manual overrides that survive re-analysis

Any hand-correction to a result is stored in `data/overrides.json`, keyed by the
change's stable `id`. These overrides are **re-applied on every export**, including
after new manuals are analyzed, so curated edits are never lost. This is the engine
behind the admin backend below.

---

## Admin backend

A local, single-user Flask app (`admin/`) provides a friendly UI for managing
content without editing files by hand. It reuses the same pipeline and only writes
through the vetted overrides path, so it can't corrupt the analysis data.

What you can do:

- **Manually update results** — edit a result's title, type, description, quotes
  (bullets), chapter, and images (add / remove / replace). Edits are saved as
  overrides and survive future re-analysis.
- **Highlight featured results** — check **Highlight** on any result to feature it
  in a **"Featured Changes Since YEAR"** section pinned to the top of that year's
  page (hidden entirely when nothing is highlighted).
- **Add a new manual PDF** — upload a `Drivers_Manual_<YYYY>.pdf` and pick:
  - **Newest Manual** — becomes the latest edition; re-analyzes every prior year
    against it.
  - **Old Manual** — an older edition; runs the single comparison against the
    current latest.
  Files must follow the naming convention, and a year already in the database is
  rejected. (LLM analysis runs locally and needs an API key.)

### Running it locally

```bash
# 1. Install pipeline + admin dependencies
pip install -r scripts/requirements.txt
pip install -r admin/requirements.txt
# For manual PDF uploads (LLM analysis), also:
#   pip install -r scripts/requirements-claude.txt
#   export ANTHROPIC_API_KEY=sk-...        # or ANALYZER_BACKEND=openai / local

# 2. Start the admin interface
python3 -m admin.app
#   → open http://localhost:5000

# 3. (optional) Preview the public site alongside it
cd web && python3 -m http.server 8080
#   → open http://localhost:8080
```

In the admin: pick a "Changes Since YEAR" page, expand a chapter, edit or highlight
results, or use the upload form to add a new manual.

### Publishing changes to the live site

The admin's top bar has two buttons:

- **Regenerate (local)** — rebuilds `web/data/*.json` from your overrides without
  pushing, so you can preview locally first.
- **Publish to GitHub** — regenerates, then commits and pushes the content files
  to the live branch so **GitHub Pages redeploys automatically** (usually within a
  minute or two).

Publish safeguards:

- It commits **only content/data** (`web/data/`, `data/overrides.json`,
  `web/images/custom/`) — never source code.
- It uses your existing local git credentials — no token setup.
- It only publishes when you're on the **`main`** branch (override with
  `PUBLISH_BRANCH`), so an unmerged branch can't reach the live site.

### Building the whole corpus from scratch (CLI)

```bash
ANTHROPIC_API_KEY=sk-... ./build.sh          # extract → analyze → export everything
python3 scripts/update_manual.py Manuals/Drivers_Manual_2028.pdf newest   # add one manual (CLI)
```

---

## Repository layout

```
Manuals/            source manual PDFs (Drivers_Manual_<YYYY>.pdf)
scripts/            Python pipeline (extract, analyze, export, overrides, LLM client)
data/               SQLite DB + overrides.json
web/                static site (index.html, app.js, styles.css, data/, images/)
admin/              Flask admin backend
build.sh            full end-to-end build
```

---

## Roadmap / future work

- **Spanish admin UI** — extend the admin backend to manage the Spanish dataset
  (`*_spanish` files / `data/manuals_spanish.db`), not just English.
- **Fully hosted admin** — deploy the admin so it can be used from any device, with
  user login / password authentication (currently local, single-user, no auth).
- **Hosted LLM analysis** — run manual-PDF ingestion and analysis on a server
  (queue/worker) instead of locally, so new manuals can be added without a laptop.
- **Broader coverage** — additional historical manuals and richer highlighting /
  ranking of featured changes.
```

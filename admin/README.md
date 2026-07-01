# RMV Manual Updates — Admin backend

A local, single-user Flask app for managing the "Changes Since YEAR" content
without touching files or the CLI by hand. It reuses the existing pipeline
(`scripts/lib/overrides.py`, `scripts/export_json.py`, `scripts/update_manual.py`)
and never changes the SQLite schema or the analysis logic.

## What it does

1. **Edit results** — change a result's title, type, description, quotes (bullets),
   chapter, and images (add / remove / replace). Edits are written to
   `data/overrides.json` and are **re-applied on every export**, so they survive
   re-analysis when new manuals are added.
2. **Highlight** — check "Highlight" on any result to feature it in the site's
   **"Featured Changes Since YEAR"** section (shown at the top of that year's page;
   hidden entirely when nothing is highlighted).
3. **Upload a manual PDF** — pick **Newest Manual** (re-analyzes every prior year
   against it and re-points all pages to it) or **Old Manual** (runs the single
   comparison against the current latest). File names must follow the convention
   `Drivers_Manual_<YYYY>.pdf`; a year already in the database is rejected.

## Run it

```bash
pip install -r admin/requirements.txt
# For manual uploads you also need the analyzer + PDF deps and an API key:
#   pip install -r scripts/requirements.txt -r scripts/requirements-claude.txt
#   export ANTHROPIC_API_KEY=sk-...        (or ANALYZER_BACKEND=openai / local)
python3 -m admin.app
```

Then open <http://localhost:5000>.

## Publishing edits

- **Text / image / highlight edits:** after saving, click **"Regenerate site data"**
  (top-right) to write the changes into `web/data/*.json`.
- **Manual uploads:** the upload job already regenerates the site data when it
  finishes; no extra step needed.
- Commit the regenerated `web/data/*.json` (and any new `web/images/custom/*`,
  `Manuals/*.pdf`, and `data/overrides.json`) and deploy the static site as usual.

## Notes / limits (v1)

- Local single-admin only; no authentication or concurrent-edit locking.
- Admin-uploaded images live in `web/images/custom/` so they survive PDF
  re-extraction (which regenerates `web/images/<year>/`).
- English dataset only for now; the code is structured so the Spanish parallel
  build (`*_spanish` files / `data/manuals_spanish.db`) can be added later.

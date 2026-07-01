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

The site is served by **GitHub Pages** off the `main` branch, so a push to `main`
auto-redeploys it. Two top-right buttons drive this:

- **Regenerate (local):** rebuilds `web/data/*.json` from your overrides *without*
  pushing. Use it to preview changes locally (`cd web && python3 -m http.server 8080`)
  before going live.
- **Publish to GitHub:** regenerates, then `git commit` + `git push` the content
  files to the live branch so Pages redeploys (usually within a minute or two).

Publish details:

- It commits **only content/data** — `web/data/`, `data/overrides.json`, and
  `web/images/custom/` — never the admin or pipeline source code.
- It uses your existing local git credentials (the same ones `git push` already
  uses); no token setup required.
- It only publishes when you're **on the `main` branch**. On any other branch it
  refuses and tells you to `git checkout main` first — this stops an unmerged
  feature branch from being pushed to the live site. (Override the target branch
  with the `PUBLISH_BRANCH` env var if Pages ever serves a different branch.)
- **Manual uploads** already regenerate `web/data/`; click **Publish to GitHub**
  afterward to push the newly added year (and its `Manuals/*.pdf` + images) live.
  Note: uploaded PDFs and `web/images/<year>/` are not in the Publish path, so a
  manual upload is best committed with a normal `git add`/`git push` (or extend
  `PUBLISH_PATHS` in `app.py`).

## Notes / limits (v1)

- Local single-admin only; no authentication or concurrent-edit locking.
- Admin-uploaded images live in `web/images/custom/` so they survive PDF
  re-extraction (which regenerates `web/images/<year>/`).
- English dataset only for now; the code is structured so the Spanish parallel
  build (`*_spanish` files / `data/manuals_spanish.db`) can be added later.

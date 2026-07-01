"""
Local CMS admin backend for the RMV Manual Updates App.

A single-user, localhost-only Flask app that wraps the existing pipeline:
  • Edit / add / delete individual update results (persisted as overrides that
    survive re-analysis — see scripts/lib/overrides.py).
  • Flag results as "Highlight" → they appear in the site's "Featured Changes"
    section.
  • Upload a new manual PDF (Old or Newest) → runs extraction + LLM analysis.

Nothing here touches the SQLite schema or the analysis logic; it only writes
through the vetted overrides.json → export_json.export_all() path (plus image
uploads to web/images/custom/ and manual PDFs to Manuals/).

Run:
    pip install -r admin/requirements.txt
    python3 -m admin.app          # → http://localhost:5000
"""

import json
import re
import sys
import threading
import uuid
from pathlib import Path

from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, send_from_directory, url_for)
from werkzeug.utils import secure_filename

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import db as database          # noqa: E402
from lib import overrides as ov         # noqa: E402
import export_json as ej                # noqa: E402
import update_manual as um              # noqa: E402

WEB_DIR = PROJECT_ROOT / "web"
WEB_DATA_DIR = WEB_DIR / "data"
IMAGES_CUSTOM_DIR = WEB_DIR / "images" / "custom"
MANUALS_DIR = PROJECT_ROOT / "Manuals"

CHANGE_TYPES = ["new", "updated", "expanded", "removed"]

app = Flask(__name__)
app.secret_key = "rmv-admin-local"  # local-only; only used for flash messages


# ── Data helpers ────────────────────────────────────────────────────────────

def load_manifest() -> dict:
    return json.loads((WEB_DATA_DIR / "manifest.json").read_text())


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "untitled"


def effective_data(from_year: int):
    """Current effective view for a from_year: fresh AI output from the DB with
    all stored overrides applied (mirrors what export_all would write). Lets the
    admin see edits/highlights immediately, without the slow full export."""
    manifest = load_manifest()
    latest = manifest["latest_year"]
    database.init_db()
    analysis = database.get_change_analysis(from_year, latest)
    fresh = {
        "from_year": from_year,
        "to_year": latest,
        "overview": analysis["overview"] if analysis else "",
        "sections": analysis["sections"] if analysis else [],
    }
    return ov.apply(from_year, fresh, ov.load_overrides()), latest


def fresh_change_by_id(from_year: int, latest: int, change_id: str):
    """The raw (pre-override) change from the DB, or None if AI didn't produce it."""
    analysis = database.get_change_analysis(from_year, latest)
    if not analysis:
        return None
    for ch in analysis["sections"]:
        if ch.get("id") == change_id:
            return ch
    return None


def group_by_chapter(sections):
    groups = {}
    for s in sections:
        ch = s.get("chapter") or "Other Updates"
        g = groups.setdefault(ch, {"chapter": ch,
                                    "chapter_num": s.get("chapter_num", 98),
                                    "changes": []})
        g["changes"].append(s)
    return sorted(groups.values(), key=lambda g: (g["chapter_num"], g["chapter"]))


def known_chapters(sections):
    seen = {}
    for s in sections:
        ch = s.get("chapter")
        if ch and ch not in seen:
            seen[ch] = s.get("chapter_num", 98)
    return sorted(seen.items(), key=lambda kv: kv[1])


# ── Serve the built site's assets (images) inside the admin ─────────────────

@app.route("/web/<path:relpath>")
def web_asset(relpath):
    return send_from_directory(WEB_DIR, relpath)


# ── Home: year list + upload form ───────────────────────────────────────────

@app.route("/")
def index():
    manifest = load_manifest()
    latest = manifest["latest_year"]
    from_years = [y for y in manifest["manual_years"] if y != latest]
    return render_template("index.html", from_years=sorted(from_years),
                           latest=latest, naming_help=um.NAMING_HELP)


# ── Year page: edit results grouped by chapter ──────────────────────────────

@app.route("/year/<int:from_year>")
def year(from_year):
    data, latest = effective_data(from_year)
    groups = group_by_chapter(data["sections"])
    n_featured = sum(1 for s in data["sections"] if s.get("highlight"))
    return render_template("year.html", from_year=from_year, latest=latest,
                           overview=data.get("overview", ""), groups=groups,
                           change_types=CHANGE_TYPES,
                           chapters=known_chapters(data["sections"]),
                           n_featured=n_featured)


# ── Save an edit to one change ──────────────────────────────────────────────

@app.route("/year/<int:from_year>/change/<change_id>/save", methods=["POST"])
def save_change(from_year, change_id):
    _, latest = effective_data(from_year)
    base = fresh_change_by_id(from_year, latest, change_id)
    is_new = base is None  # a hand-added change has no DB counterpart

    submitted = {
        "title": request.form.get("title", "").strip(),
        "change_type": request.form.get("change_type", "").strip(),
        "description": request.form.get("description", "").strip(),
        "chapter": request.form.get("chapter", "").strip(),
        "bullets": [b.strip() for b in request.form.get("bullets", "").splitlines()
                    if b.strip()],
        "images": _collect_images(request),
    }
    # chapter_num follows the chosen chapter (kept consistent with the site's grouping).
    chapter_num = request.form.get("chapter_num", "").strip()
    if chapter_num.isdigit():
        submitted["chapter_num"] = int(chapter_num)

    highlight = request.form.get("highlight") == "on"

    overrides = ov.load_overrides()
    changes = overrides["pairs"].setdefault(str(from_year), {}).setdefault("changes", {})

    if is_new:
        fields = {k: v for k, v in submitted.items() if v not in ("", [], None)}
        if highlight:
            fields["highlight"] = True
        changes[change_id] = {"action": "add", "fields": fields}
    else:
        # Only fields that differ from the AI output become overrides, so
        # untouched fields stay open to future AI improvements.
        fields = {k: v for k, v in submitted.items() if v != base.get(k)}
        if highlight:
            fields["highlight"] = True  # never in AI output, so always an override
        if fields:
            changes[change_id] = {"action": "edit", "fields": fields}
        else:
            changes.pop(change_id, None)  # fully reverted → drop the override

    ov.save_overrides(overrides)
    flash(f"Saved “{submitted['title'] or change_id}”. Click "
          f"“Regenerate site data” to publish to the live site.", "ok")
    return redirect(url_for("year", from_year=from_year) + f"#c-{change_id}")


def _collect_images(request):
    """Rebuild a change's image list from the form: existing images that weren't
    marked for removal, plus any newly uploaded files (saved to images/custom/)."""
    images = []
    idx = 0
    while f"img_src_{idx}" in request.form:
        if request.form.get(f"img_remove_{idx}") != "on":
            images.append({
                "src": request.form.get(f"img_src_{idx}", ""),
                "alt": request.form.get(f"img_alt_{idx}", ""),
                "caption": request.form.get(f"img_caption_{idx}", ""),
            })
        idx += 1

    IMAGES_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    for file in request.files.getlist("new_images"):
        if not file or not file.filename:
            continue
        safe = secure_filename(file.filename)
        dest = IMAGES_CUSTOM_DIR / f"{uuid.uuid4().hex[:8]}_{safe}"
        file.save(dest)
        images.append({"src": f"images/custom/{dest.name}", "alt": "", "caption": ""})
    return images


# ── Quick highlight toggle (no full re-export) ──────────────────────────────

@app.route("/year/<int:from_year>/change/<change_id>/highlight", methods=["POST"])
def toggle_highlight(from_year, change_id):
    on = request.form.get("highlight") == "on"
    if on:
        ov.set_change_override(from_year, change_id, {"highlight": True})
    else:
        ov.remove_change_field_override(from_year, change_id, "highlight")
    return redirect(url_for("year", from_year=from_year) + f"#c-{change_id}")


# ── Delete a change ─────────────────────────────────────────────────────────

@app.route("/year/<int:from_year>/change/<change_id>/delete", methods=["POST"])
def delete_change(from_year, change_id):
    ov.delete_change_override(from_year, change_id)
    flash(f"Deleted “{change_id}”. Regenerate to publish.", "ok")
    return redirect(url_for("year", from_year=from_year))


# ── Add a brand-new change ──────────────────────────────────────────────────

@app.route("/year/<int:from_year>/change/add", methods=["POST"])
def add_change(from_year):
    title = request.form.get("title", "").strip()
    if not title:
        flash("A title is required to add a result.", "error")
        return redirect(url_for("year", from_year=from_year))
    change_id = slugify(title)
    fields = {
        "title": title,
        "change_type": request.form.get("change_type", "new").strip() or "new",
        "description": request.form.get("description", "").strip(),
        "chapter": request.form.get("chapter", "").strip(),
        "bullets": [b.strip() for b in request.form.get("bullets", "").splitlines()
                    if b.strip()],
        "images": [],
    }
    chapter_num = request.form.get("chapter_num", "").strip()
    if chapter_num.isdigit():
        fields["chapter_num"] = int(chapter_num)
    if request.form.get("highlight") == "on":
        fields["highlight"] = True
    ov.add_change_override(from_year, change_id, fields)
    flash(f"Added “{title}”. Regenerate to publish.", "ok")
    return redirect(url_for("year", from_year=from_year) + f"#c-{change_id}")


# ── Regenerate the static site data (applies all overrides) ─────────────────

@app.route("/regenerate", methods=["POST"])
def regenerate():
    try:
        ej.export_all()
        flash("Site data regenerated. web/data/*.json is up to date.", "ok")
    except Exception as e:  # noqa: BLE001
        flash(f"Regeneration failed: {e}", "error")
    return redirect(request.referrer or url_for("index"))


# ── Upload a new manual PDF (background job) ────────────────────────────────

JOBS: dict = {}


def _run_add_manual(job_id, pdf_path, mode):
    job = JOBS[job_id]
    try:
        result = um.add_manual(pdf_path, mode, log=lambda m: job["log"].append(str(m)))
        job["status"] = "success"
        job["result"] = result
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
        job["log"].append(f"ERROR: {e}")


@app.route("/upload-manual", methods=["POST"])
def upload_manual():
    file = request.files.get("pdf")
    mode = request.form.get("mode", "")
    if not file or not file.filename:
        flash("Choose a PDF file to upload.", "error")
        return redirect(url_for("index"))
    if mode not in ("old", "newest"):
        flash("Choose Old Manual or Newest Manual.", "error")
        return redirect(url_for("index"))

    # Validate the naming convention up-front for a clear error.
    try:
        year_num = um.validate_filename(Path(file.filename))
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("index"))

    database.init_db()
    if year_num in database.get_all_manual_years():
        flash("Error - that manual is already in the database", "error")
        return redirect(url_for("index"))

    MANUALS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MANUALS_DIR / f"Drivers_Manual_{year_num}.pdf"
    file.save(dest)

    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {"status": "running", "log": [], "year": year_num, "mode": mode}
    threading.Thread(target=_run_add_manual, args=(job_id, dest, mode),
                     daemon=True).start()
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/job/<job_id>")
def job_page(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    return render_template("job.html", job_id=job_id, job=job)


@app.route("/job/<job_id>/status")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        abort(404)
    return jsonify(job)


if __name__ == "__main__":
    # Reloader disabled so background upload jobs (and the in-memory JOBS map)
    # survive across requests.
    app.run(host="127.0.0.1", port=5000, debug=True, use_reloader=False)

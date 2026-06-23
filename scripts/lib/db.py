import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DEFAULT_DB_PATH = Path(__file__).parent.parent.parent / "data" / "manuals.db"

# The DB path can be overridden via the MANUALS_DB env var so a parallel build
# (e.g. the Spanish edition) can use a separate store and avoid year collisions
# with the English data. Defaults to the original English DB.
DB_PATH = Path(os.environ["MANUALS_DB"]) if os.environ.get("MANUALS_DB") else _DEFAULT_DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS manuals (
                year     INTEGER PRIMARY KEY,
                added_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                year          INTEGER NOT NULL REFERENCES manuals(year),
                chapter_num   INTEGER NOT NULL,
                chapter_title TEXT    NOT NULL,
                section_key   TEXT    NOT NULL,
                title         TEXT    NOT NULL,
                page          INTEGER NOT NULL,
                body_text     TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS images (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                section_id INTEGER NOT NULL REFERENCES sections(id),
                src_path   TEXT    NOT NULL,
                alt_text   TEXT    NOT NULL DEFAULT '',
                caption    TEXT    NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS change_analyses (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                from_year     INTEGER NOT NULL,
                to_year       INTEGER NOT NULL,
                computed_at   TEXT    NOT NULL,
                overview_text TEXT    NOT NULL,
                sections_json TEXT    NOT NULL,
                UNIQUE(from_year, to_year)
            );

            -- One row per individual analysis run for a pair. The canonical
            -- change_analyses row is the MERGE of all runs (see lib/merge.py);
            -- keeping the raw runs lets coverage accumulate across re-runs.
            CREATE TABLE IF NOT EXISTS change_analysis_runs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                from_year     INTEGER NOT NULL,
                to_year       INTEGER NOT NULL,
                computed_at   TEXT    NOT NULL,
                sections_json TEXT    NOT NULL
            );
        """)


def insert_manual(year: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO manuals (year, added_at) VALUES (?, ?)",
            (year, datetime.now(timezone.utc).isoformat()),
        )


def insert_section(
    year: int,
    chapter_num: int,
    chapter_title: str,
    section_key: str,
    title: str,
    page: int,
    body_text: str,
) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO sections
               (year, chapter_num, chapter_title, section_key, title, page, body_text)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (year, chapter_num, chapter_title, section_key, title, page, body_text),
        )
        return cur.lastrowid


def insert_image(section_id: int, src_path: str, alt_text: str = "", caption: str = "") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO images (section_id, src_path, alt_text, caption) VALUES (?, ?, ?, ?)",
            (section_id, src_path, alt_text, caption),
        )


def upsert_change_analysis(
    from_year: int, to_year: int, overview_text: str, sections: list
) -> None:
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO change_analyses
               (from_year, to_year, computed_at, overview_text, sections_json)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(from_year, to_year) DO UPDATE SET
                 computed_at   = excluded.computed_at,
                 overview_text = excluded.overview_text,
                 sections_json = excluded.sections_json""",
            (
                from_year,
                to_year,
                datetime.now(timezone.utc).isoformat(),
                overview_text,
                json.dumps(sections),
            ),
        )


def get_change_analysis(from_year: int, to_year: int) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM change_analyses WHERE from_year=? AND to_year=?",
            (from_year, to_year),
        ).fetchone()
    if row is None:
        return None
    return {
        "from_year": row["from_year"],
        "to_year": row["to_year"],
        "overview": row["overview_text"],
        "sections": json.loads(row["sections_json"]),
    }


# ── Analysis runs (raw, pre-merge) ──────────────────────────────────────────────

def insert_analysis_run(from_year: int, to_year: int, sections: list) -> None:
    """Append one raw analysis run for a pair. Coverage accumulates across runs."""
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO change_analysis_runs
               (from_year, to_year, computed_at, sections_json)
               VALUES (?, ?, ?, ?)""",
            (from_year, to_year, datetime.now(timezone.utc).isoformat(), json.dumps(sections)),
        )


def get_analysis_runs(from_year: int, to_year: int) -> list[list]:
    """All raw runs for a pair, oldest first (so the earliest occurrence wins its id)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT sections_json FROM change_analysis_runs "
            "WHERE from_year=? AND to_year=? ORDER BY id",
            (from_year, to_year),
        ).fetchall()
    return [json.loads(r["sections_json"]) for r in rows]


def count_analysis_runs(from_year: int, to_year: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM change_analysis_runs WHERE from_year=? AND to_year=?",
            (from_year, to_year),
        ).fetchone()
    return row["n"]


def clear_analysis_runs(from_year: int, to_year: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM change_analysis_runs WHERE from_year=? AND to_year=?",
            (from_year, to_year),
        )


def get_all_manual_years() -> list[int]:
    with get_connection() as conn:
        rows = conn.execute("SELECT year FROM manuals ORDER BY year").fetchall()
    return [r["year"] for r in rows]


def get_sections_for_year(year: int) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT s.*, GROUP_CONCAT(i.src_path, '||') AS image_paths
               FROM sections s
               LEFT JOIN images i ON i.section_id = s.id
               WHERE s.year = ?
               GROUP BY s.id
               ORDER BY s.chapter_num, s.page""",
            (year,),
        ).fetchall()
    result = []
    for r in rows:
        images = []
        if r["image_paths"]:
            for p in r["image_paths"].split("||"):
                images.append({"src": p, "alt": "", "caption": ""})
        result.append({
            "id": r["id"],
            "chapter_num": r["chapter_num"],
            "chapter_title": r["chapter_title"],
            "section_key": r["section_key"],
            "title": r["title"],
            "page": r["page"],
            "body_text": r["body_text"],
            "images": images,
        })
    return result


def year_exists(year: int) -> bool:
    with get_connection() as conn:
        row = conn.execute("SELECT 1 FROM manuals WHERE year=?", (year,)).fetchone()
    return row is not None


def delete_year_data(year: int) -> None:
    """Remove all data for a year so it can be re-extracted."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM images WHERE section_id IN (SELECT id FROM sections WHERE year=?)",
            (year,),
        )
        conn.execute("DELETE FROM sections WHERE year=?", (year,))
        conn.execute("DELETE FROM manuals WHERE year=?", (year,))

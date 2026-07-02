"""SQLite storage for monthly IKR goals and progress."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from auth import ensure_admin_user
from config import (
    GOAL_TYPE_ACCUMULATE,
    DAILY_MODE_DO,
    GOALS_CONFIG_PATH,
    IKRR_DB_PATH,
    PROGRESS_PATH,
    ensure_db_file,
    new_goal_id,
)

_DB_INITIALIZED = False
_JSON_MIGRATION_CHECKED: set[str] = set()


def _persist_to_cloud() -> None:
    from gcs_sidecar import persist_ikr_db_to_cloud

    persist_ikr_db_to_cloud()

_GOALS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS goals (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    name TEXT NOT NULL,
    target REAL NOT NULL DEFAULT 0,
    weightage REAL NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""

_GOALS_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS idx_goals_user_month ON goals(user_id, month_key);
"""

_PROGRESS_DDL = """
CREATE TABLE IF NOT EXISTS progress (
    goal_id TEXT PRIMARY KEY,
    month_key TEXT NOT NULL,
    value REAL NOT NULL DEFAULT 0,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_progress_month ON progress(month_key);
"""

_PROGRESS_LOG_DDL = """
CREATE TABLE IF NOT EXISTS progress_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    goal_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    value REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'app',
    recorded_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_progress_log_user_month ON progress_log(user_id, month_key);
CREATE INDEX IF NOT EXISTS idx_progress_log_goal ON progress_log(goal_id, recorded_at);
"""

_DAILY_LOG_DDL = """
CREATE TABLE IF NOT EXISTS daily_log (
    goal_id TEXT NOT NULL,
    log_date TEXT NOT NULL,
    entry TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'app',
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (goal_id, log_date),
    FOREIGN KEY (goal_id) REFERENCES goals(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_daily_log_goal ON daily_log(goal_id);
"""

_MONTH_SUMMARY_DDL = """
CREATE TABLE IF NOT EXISTS month_summary (
    user_id TEXT NOT NULL,
    month_key TEXT NOT NULL,
    goal_count INTEGER NOT NULL DEFAULT 0,
    goals_completed INTEGER NOT NULL DEFAULT 0,
    overall_pct REAL NOT NULL DEFAULT 0,
    earned REAL NOT NULL DEFAULT 0,
    total_weight REAL NOT NULL DEFAULT 0,
    overall_status TEXT NOT NULL DEFAULT '',
    overall_tone TEXT NOT NULL DEFAULT '',
    goals_json TEXT NOT NULL DEFAULT '[]',
    score_as_of_date TEXT NOT NULL DEFAULT '',
    finalized_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (user_id, month_key),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_month_summary_user ON month_summary(user_id);
"""


def _connect() -> sqlite3.Connection:
    ensure_db_file()
    conn = sqlite3.connect(IKRR_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    except sqlite3.Error:
        return set()
    return {str(r[1]) for r in rows}


def _migrate_goals_user_id(conn: sqlite3.Connection, admin_id: str) -> None:
    cols = _table_columns(conn, "goals")
    if not cols or "user_id" in cols:
        return
    conn.execute("ALTER TABLE goals ADD COLUMN user_id TEXT")
    conn.execute("UPDATE goals SET user_id = ? WHERE user_id IS NULL", (admin_id,))


def _migrate_goals_extra_columns(conn: sqlite3.Connection) -> None:
    cols = _table_columns(conn, "goals")
    if not cols:
        return
    if "category" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    if "notes" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
    if "goal_type" not in cols:
        conn.execute(
            "ALTER TABLE goals ADD COLUMN goal_type TEXT NOT NULL DEFAULT 'accumulate'"
        )
    if "baseline" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN baseline REAL NOT NULL DEFAULT 0")
    if "unit" not in cols:
        conn.execute("ALTER TABLE goals ADD COLUMN unit TEXT NOT NULL DEFAULT ''")
    if "daily_mode" not in cols:
        conn.execute(
            "ALTER TABLE goals ADD COLUMN daily_mode TEXT NOT NULL DEFAULT 'do'"
        )


def init_db(*, force: bool = False) -> None:
    """Create ikr.db and all tables if missing. Safe to call on every startup."""
    global _DB_INITIALIZED
    if _DB_INITIALIZED and not force:
        return
    ensure_db_file()
    admin_id = ensure_admin_user()
    with _connect() as conn:
        goal_cols = _table_columns(conn, "goals")
        if not goal_cols:
            conn.executescript(_GOALS_TABLE_DDL)
        else:
            _migrate_goals_user_id(conn, admin_id)
            _migrate_goals_extra_columns(conn)
        conn.executescript(
            _GOALS_INDEX_DDL
            + _PROGRESS_DDL
            + _PROGRESS_LOG_DDL
            + _DAILY_LOG_DDL
            + _MONTH_SUMMARY_DDL
        )
        conn.commit()
    _DB_INITIALIZED = True


def ensure_database() -> None:
    init_db()


def _migrate_json_if_needed(user_id: str) -> None:
    if user_id in _JSON_MIGRATION_CHECKED:
        return
    _JSON_MIGRATION_CHECKED.add(user_id)
    init_db()
    with _connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM goals WHERE user_id = ?",
            (user_id,),
        ).fetchone()[0]
        if count > 0:
            return

    total_goals = 0
    with _connect() as conn:
        total_goals = conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0]
    if total_goals > 0:
        return

    if GOALS_CONFIG_PATH.is_file():
        try:
            with GOALS_CONFIG_PATH.open(encoding="utf-8") as f:
                cfg = json.load(f)
            months = cfg.get("months") or {}
            for month_key, month_data in months.items():
                goals = month_data.get("goals") or []
                rows: list[dict] = []
                for i, g in enumerate(goals):
                    if not isinstance(g, dict):
                        continue
                    name = str(g.get("name", "")).strip()
                    if not name:
                        continue
                    rows.append(
                        {
                            "id": str(g.get("id", "")).strip() or new_goal_id(),
                            "name": name,
                            "target": float(g.get("target", 0) or 0),
                            "weightage": float(g.get("weightage", 0) or 0),
                            "category": str(g.get("category", "") or ""),
                            "notes": str(g.get("notes", "") or ""),
                            "sort_order": i,
                        }
                    )
                if rows:
                    save_month_goals(user_id, month_key, rows, force=True)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass

    if PROGRESS_PATH.is_file():
        try:
            with PROGRESS_PATH.open(encoding="utf-8") as f:
                prog = json.load(f)
            months = prog.get("months") or {}
            for month_key, month_data in months.items():
                values = month_data.get("goals") or {}
                if isinstance(values, dict):
                    save_month_progress(
                        user_id, month_key, values, source="import", force=True
                    )
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass


def list_configured_months(user_id: str) -> list[str]:
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT month_key
            FROM goals
            WHERE user_id = ?
            ORDER BY month_key DESC
            """,
            (user_id,),
        ).fetchall()
    return [str(r["month_key"]) for r in rows]


def _goal_row_to_dict(r: sqlite3.Row) -> dict:
    from goal_scoring import normalize_goal

    name = str(r["name"]).strip()
    if not name:
        return {}
    return normalize_goal(
        {
            "id": str(r["id"]),
            "name": name,
            "target": max(float(r["target"]), 0.0),
            "weightage": max(float(r["weightage"]), 0.0),
            "category": str(r["category"] or ""),
            "notes": str(r["notes"] or ""),
            "goal_type": str(r["goal_type"] if "goal_type" in r.keys() else GOAL_TYPE_ACCUMULATE),
            "baseline": float(r["baseline"] if "baseline" in r.keys() else 0.0),
            "unit": str(r["unit"] if "unit" in r.keys() else ""),
            "daily_mode": str(r["daily_mode"] if "daily_mode" in r.keys() else DAILY_MODE_DO),
        }
    )


def fetch_month_goals(user_id: str, month_key: str) -> list[dict]:
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, target, weightage, sort_order, category, notes,
                   goal_type, baseline, unit, daily_mode
            FROM goals
            WHERE user_id = ? AND month_key = ?
            ORDER BY sort_order, name
            """,
            (user_id, month_key),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        g = _goal_row_to_dict(r)
        if g:
            out.append(g)
    return out


def draft_rows_for_month(user_id: str, month_key: str) -> list[dict]:
    goals = fetch_month_goals(user_id, month_key)
    if goals:
        return [
            {
                "id": g["id"],
                "goal": g["name"],
                "target": g["target"],
                "weightage": g["weightage"],
                "category": g.get("category", ""),
                "notes": g.get("notes", ""),
                "goal_type": g.get("goal_type", GOAL_TYPE_ACCUMULATE),
                "baseline": g.get("baseline", 0.0),
                "unit": g.get("unit", ""),
                "daily_mode": g.get("daily_mode", DAILY_MODE_DO),
            }
            for g in goals
        ]
    return [
        {
            "id": new_goal_id(),
            "goal": "",
            "target": 1.0,
            "weightage": 0.0,
            "category": "",
            "notes": "",
            "goal_type": GOAL_TYPE_ACCUMULATE,
            "baseline": 0.0,
            "unit": "",
            "daily_mode": DAILY_MODE_DO,
        }
    ]


def save_month_goals(
    user_id: str,
    month_key: str,
    goals: list[dict],
    *,
    force: bool = False,
) -> tuple[bool, str]:
    from config import config_edit_status

    if not force:
        ok, msg = config_edit_status(month_key)
        if not ok:
            return False, msg

    init_db()
    with _connect() as conn:
        existing_rows = conn.execute(
            "SELECT id FROM goals WHERE user_id = ? AND month_key = ?",
            (user_id, month_key),
        ).fetchall()
        existing_ids = {str(r["id"]) for r in existing_rows}
        new_ids = {str(g["id"]) for g in goals}

        for old_id in existing_ids - new_ids:
            conn.execute("DELETE FROM progress WHERE goal_id = ?", (old_id,))
            conn.execute("DELETE FROM progress_log WHERE goal_id = ?", (old_id,))
            conn.execute("DELETE FROM daily_log WHERE goal_id = ?", (old_id,))
            conn.execute("DELETE FROM goals WHERE id = ?", (old_id,))

        conn.execute(
            "DELETE FROM goals WHERE user_id = ? AND month_key = ?",
            (user_id, month_key),
        )
        for i, g in enumerate(goals):
            conn.execute(
                """
                INSERT INTO goals (
                    id, user_id, month_key, name, target, weightage,
                    sort_order, category, notes, goal_type, baseline, unit, daily_mode
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(g["id"]),
                    user_id,
                    month_key,
                    str(g["name"]).strip(),
                    max(float(g["target"]), 0.0),
                    max(float(g["weightage"]), 0.0),
                    i,
                    str(g.get("category", "") or "").strip(),
                    str(g.get("notes", "") or "").strip(),
                    str(g.get("goal_type") or GOAL_TYPE_ACCUMULATE),
                    max(float(g.get("baseline") or 0.0), 0.0),
                    str(g.get("unit") or "").strip(),
                    str(g.get("daily_mode") or DAILY_MODE_DO),
                ),
            )
        conn.execute(
            "DELETE FROM month_summary WHERE user_id = ? AND month_key = ?",
            (user_id, month_key),
        )
        conn.commit()
    _persist_to_cloud()
    return True, "Saved."


def fetch_month_summary(user_id: str, month_key: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT user_id, month_key, goal_count, goals_completed, overall_pct,
                   earned, total_weight, overall_status, overall_tone,
                   goals_json, score_as_of_date, finalized_at
            FROM month_summary
            WHERE user_id = ? AND month_key = ?
            """,
            (user_id, month_key),
        ).fetchone()
    if row is None:
        return None
    return dict(row)


def save_month_summary(user_id: str, month_key: str, record: dict) -> None:
    init_db()
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO month_summary (
                user_id, month_key, goal_count, goals_completed, overall_pct,
                earned, total_weight, overall_status, overall_tone,
                goals_json, score_as_of_date, finalized_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, month_key) DO UPDATE SET
                goal_count = excluded.goal_count,
                goals_completed = excluded.goals_completed,
                overall_pct = excluded.overall_pct,
                earned = excluded.earned,
                total_weight = excluded.total_weight,
                overall_status = excluded.overall_status,
                overall_tone = excluded.overall_tone,
                goals_json = excluded.goals_json,
                score_as_of_date = excluded.score_as_of_date,
                finalized_at = excluded.finalized_at
            """,
            (
                user_id,
                month_key,
                int(record.get("goal_count", 0)),
                int(record.get("goals_completed", 0)),
                float(record.get("overall_pct", 0.0)),
                float(record.get("earned", 0.0)),
                float(record.get("total_weight", 0.0)),
                str(record.get("overall_status", "")),
                str(record.get("overall_tone", "")),
                json.dumps(record.get("goals", [])),
                str(record.get("score_as_of_date", "")),
                now,
            ),
        )
        conn.commit()
    _persist_to_cloud()


def delete_month_summary(user_id: str, month_key: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "DELETE FROM month_summary WHERE user_id = ? AND month_key = ?",
            (user_id, month_key),
        )
        conn.commit()


def fetch_month_progress(user_id: str, month_key: str) -> dict[str, float]:
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT p.goal_id, p.value
            FROM progress p
            JOIN goals g ON g.id = p.goal_id
            WHERE p.month_key = ? AND g.user_id = ?
            """,
            (month_key, user_id),
        ).fetchall()
    out: dict[str, float] = {}
    for r in rows:
        try:
            out[str(r["goal_id"])] = max(float(r["value"]), 0.0)
        except (TypeError, ValueError):
            out[str(r["goal_id"])] = 0.0
    return out


def log_progress_history(
    user_id: str,
    month_key: str,
    progress_by_id: dict[str, float],
    *,
    source: str = "app",
) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        for goal_id, value in progress_by_id.items():
            owned = conn.execute(
                "SELECT 1 FROM goals WHERE id = ? AND user_id = ? AND month_key = ?",
                (str(goal_id), user_id, month_key),
            ).fetchone()
            if not owned:
                continue
            conn.execute(
                """
                INSERT INTO progress_log (user_id, goal_id, month_key, value, source, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, str(goal_id), month_key, max(float(value), 0.0), source, now),
            )
        conn.commit()


def fetch_progress_log_timeline(user_id: str, month_key: str) -> list[dict]:
    """All log entries for a month, oldest first (for timeline charts)."""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT goal_id, value, recorded_at
            FROM progress_log
            WHERE user_id = ? AND month_key = ?
            ORDER BY recorded_at ASC
            """,
            (user_id, month_key),
        ).fetchall()
    return [
        {
            "goal_id": str(r["goal_id"]),
            "value": float(r["value"]),
            "recorded_at": str(r["recorded_at"]),
        }
        for r in rows
    ]


def fetch_progress_history(
    user_id: str,
    month_key: str,
    *,
    goal_id: str | None = None,
    limit: int = 200,
) -> list[dict]:
    init_db()
    query = """
        SELECT pl.goal_id, g.name AS goal_name, pl.value, pl.source, pl.recorded_at
        FROM progress_log pl
        JOIN goals g ON g.id = pl.goal_id
        WHERE pl.user_id = ? AND pl.month_key = ?
    """
    params: list = [user_id, month_key]
    if goal_id:
        query += " AND pl.goal_id = ?"
        params.append(goal_id)
    query += " ORDER BY pl.recorded_at DESC LIMIT ?"
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    return [
        {
            "goal_id": str(r["goal_id"]),
            "goal_name": str(r["goal_name"]),
            "value": float(r["value"]),
            "source": str(r["source"]),
            "recorded_at": str(r["recorded_at"]),
        }
        for r in rows
    ]


def save_month_progress(
    user_id: str,
    month_key: str,
    progress_by_id: dict[str, float],
    *,
    source: str = "app",
    force: bool = False,
) -> tuple[bool, str]:
    from config import progress_edit_status

    if not force:
        ok, msg = progress_edit_status(month_key)
        if not ok:
            return False, msg

    init_db()
    with _connect() as conn:
        conn.execute(
            """
            DELETE FROM progress
            WHERE month_key = ?
              AND goal_id IN (
                  SELECT id FROM goals WHERE user_id = ? AND month_key = ?
              )
            """,
            (month_key, user_id, month_key),
        )
        for goal_id, value in progress_by_id.items():
            owned = conn.execute(
                """
                SELECT 1 FROM goals
                WHERE id = ? AND user_id = ? AND month_key = ?
                """,
                (str(goal_id), user_id, month_key),
            ).fetchone()
            if not owned:
                continue
            conn.execute(
                """
                INSERT INTO progress (goal_id, month_key, value)
                VALUES (?, ?, ?)
                """,
                (str(goal_id), month_key, max(float(value), 0.0)),
            )
        conn.commit()

    log_progress_history(user_id, month_key, progress_by_id, source=source)

    from notifications import record_progress_saved

    record_progress_saved(user_id)
    _persist_to_cloud()
    return True, "Saved."


def fetch_daily_log(user_id: str, month_key: str, goal_id: str | None = None) -> dict[str, dict[str, str]]:
    """Return {goal_id: {YYYY-MM-DD: 'yes'|'no'}} for the month."""
    init_db()
    query = """
        SELECT dl.goal_id, dl.log_date, dl.entry
        FROM daily_log dl
        JOIN goals g ON g.id = dl.goal_id
        WHERE g.user_id = ? AND g.month_key = ?
    """
    params: list = [user_id, month_key]
    if goal_id:
        query += " AND dl.goal_id = ?"
        params.append(goal_id)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        gid = str(r["goal_id"])
        out.setdefault(gid, {})[str(r["log_date"])] = str(r["entry"]).lower()
    return out


def save_daily_entry(
    user_id: str,
    month_key: str,
    goal_id: str,
    log_date: str,
    entry: str,
    *,
    source: str = "app",
) -> tuple[bool, str]:
    """Upsert one daily yes/no. log_date = YYYY-MM-DD. Returns (ok, message)."""
    from datetime import date as date_cls

    from config import GOAL_TYPE_DAILY
    from goal_scoring import DAILY_NO, DAILY_YES, valid_log_date
    from config import progress_edit_status

    ok, lock_msg = progress_edit_status(month_key)
    if not ok:
        return False, lock_msg

    init_db()
    entry = entry.strip().lower()
    if entry not in (DAILY_YES, DAILY_NO):
        return False, "Entry must be yes or no."

    try:
        parsed = date_cls.fromisoformat(log_date)
    except ValueError:
        return False, "Invalid date."

    if not valid_log_date(month_key, parsed):
        return False, "Date must be in this month and not in the future."

    with _connect() as conn:
        row = conn.execute(
            """
            SELECT id, goal_type FROM goals
            WHERE id = ? AND user_id = ? AND month_key = ?
            """,
            (goal_id, user_id, month_key),
        ).fetchone()
        if not row:
            return False, "Goal not found."
        if str(row["goal_type"]) != GOAL_TYPE_DAILY:
            return False, "Not a daily log goal."

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.execute(
            """
            INSERT INTO daily_log (goal_id, log_date, entry, source, recorded_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(goal_id, log_date) DO UPDATE SET
                entry = excluded.entry,
                source = excluded.source,
                recorded_at = excluded.recorded_at
            """,
            (goal_id, log_date, entry, source, now),
        )
        conn.commit()

    sync_daily_progress(user_id, month_key, goal_id, source=source)
    _persist_to_cloud()
    return True, "Saved."


def sync_daily_progress(
    user_id: str,
    month_key: str,
    goal_id: str,
    *,
    source: str = "app",
) -> None:
    """Update progress table from daily_log counts."""
    from config import GOAL_TYPE_DAILY
    from goal_scoring import summarize_daily_log

    goals = fetch_month_goals(user_id, month_key)
    goal = next((g for g in goals if g["id"] == goal_id), None)
    if not goal or goal["goal_type"] != GOAL_TYPE_DAILY:
        return

    entries = fetch_daily_log(user_id, month_key, goal_id).get(goal_id, {})
    summary = summarize_daily_log(goal["daily_mode"], entries, month_key=month_key)
    value = float(summary["good_days"])

    progress = fetch_month_progress(user_id, month_key)
    progress[goal_id] = value
    save_month_progress(user_id, month_key, {goal_id: value}, source=source)


def month_summary(user_id: str) -> list[tuple[str, int, float]]:
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT month_key, COUNT(*) AS n, COALESCE(SUM(weightage), 0) AS total_w
            FROM goals
            WHERE user_id = ?
            GROUP BY month_key
            ORDER BY month_key DESC
            """,
            (user_id,),
        ).fetchall()
    return [(str(r["month_key"]), int(r["n"]), float(r["total_w"])) for r in rows]

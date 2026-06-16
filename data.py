"""SQLite storage for monthly IKR goals and progress."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from auth import ensure_admin_user
from config import (
    GOALS_CONFIG_PATH,
    IKRR_DB_PATH,
    PROGRESS_PATH,
    ensure_db_file,
    new_goal_id,
)

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


def init_db() -> None:
    """Create ikr.db and all tables if missing. Safe to call on every startup."""
    ensure_db_file()
    admin_id = ensure_admin_user()
    with _connect() as conn:
        goal_cols = _table_columns(conn, "goals")
        if not goal_cols:
            conn.executescript(_GOALS_TABLE_DDL)
        else:
            _migrate_goals_user_id(conn, admin_id)
            _migrate_goals_extra_columns(conn)
        conn.executescript(_GOALS_INDEX_DDL + _PROGRESS_DDL + _PROGRESS_LOG_DDL)
        conn.commit()


def ensure_database() -> None:
    init_db()


def _migrate_json_if_needed(user_id: str) -> None:
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
                    save_month_goals(user_id, month_key, rows)
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
                    save_month_progress(user_id, month_key, values, source="import")
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


def fetch_month_goals(user_id: str, month_key: str) -> list[dict]:
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, target, weightage, sort_order, category, notes
            FROM goals
            WHERE user_id = ? AND month_key = ?
            ORDER BY sort_order, name
            """,
            (user_id, month_key),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        name = str(r["name"]).strip()
        if not name:
            continue
        out.append(
            {
                "id": str(r["id"]),
                "name": name,
                "target": max(float(r["target"]), 0.0),
                "weightage": max(float(r["weightage"]), 0.0),
                "category": str(r["category"] or ""),
                "notes": str(r["notes"] or ""),
            }
        )
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
        }
    ]


def save_month_goals(user_id: str, month_key: str, goals: list[dict]) -> None:
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
                    sort_order, category, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
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
) -> None:
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

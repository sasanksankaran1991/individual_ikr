"""SQLite storage for monthly IKR goals and progress."""

from __future__ import annotations

import json
import sqlite3

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
        conn.executescript(_GOALS_INDEX_DDL + _PROGRESS_DDL)
        conn.commit()


def ensure_database() -> None:
    """Public alias — guarantees a usable database exists."""
    init_db()


def _migrate_json_if_needed(user_id: str) -> None:
    """One-time import from legacy JSON files when this user has no goals."""
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
                    save_month_progress(user_id, month_key, values)
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
    """Return saved goals for a user/month (non-empty names only)."""
    _migrate_json_if_needed(user_id)
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, name, target, weightage, sort_order
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
            }
        )
    return out


def draft_rows_for_month(user_id: str, month_key: str) -> list[dict]:
    """Rows for the config editor, including one blank row when none exist."""
    goals = fetch_month_goals(user_id, month_key)
    if goals:
        return [
            {
                "id": g["id"],
                "goal": g["name"],
                "target": g["target"],
                "weightage": g["weightage"],
            }
            for g in goals
        ]
    return [
        {
            "id": new_goal_id(),
            "goal": "",
            "target": 1.0,
            "weightage": 0.0,
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
            conn.execute("DELETE FROM goals WHERE id = ?", (old_id,))

        conn.execute(
            "DELETE FROM goals WHERE user_id = ? AND month_key = ?",
            (user_id, month_key),
        )
        for i, g in enumerate(goals):
            conn.execute(
                """
                INSERT INTO goals (id, user_id, month_key, name, target, weightage, sort_order)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(g["id"]),
                    user_id,
                    month_key,
                    str(g["name"]).strip(),
                    max(float(g["target"]), 0.0),
                    max(float(g["weightage"]), 0.0),
                    i,
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


def save_month_progress(
    user_id: str, month_key: str, progress_by_id: dict[str, float]
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

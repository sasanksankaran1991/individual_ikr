"""Export and backup helpers."""

from __future__ import annotations

import csv
import io
from pathlib import Path

from config import IKRR_DB_PATH, format_month_label
from data import fetch_month_goals, fetch_month_progress, init_db


def read_database_bytes() -> bytes | None:
    init_db()
    if not IKRR_DB_PATH.is_file():
        return None
    return IKRR_DB_PATH.read_bytes()


def export_month_csv(user_id: str, month_key: str) -> str:
    """CSV string: goals with current progress."""
    goals = fetch_month_goals(user_id, month_key)
    progress = fetch_month_progress(user_id, month_key)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["month", "goal", "category", "target", "weightage", "progress", "notes"]
    )
    for g in goals:
        writer.writerow(
            [
                format_month_label(month_key),
                g["name"],
                g.get("category", ""),
                g["target"],
                g["weightage"],
                progress.get(g["id"], 0.0),
                g.get("notes", ""),
            ]
        )
    return buf.getvalue()


def export_all_users_csv() -> str:
    """Admin: all users' current month goals."""
    from auth import list_users
    from config import current_month_key

    month_key = current_month_key()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["username", "month", "goal", "category", "target", "weightage", "progress"]
    )
    for user in list_users():
        uid = user["id"]
        goals = fetch_month_goals(uid, month_key)
        progress = fetch_month_progress(uid, month_key)
        for g in goals:
            writer.writerow(
                [
                    user["username"],
                    format_month_label(month_key),
                    g["name"],
                    g.get("category", ""),
                    g["target"],
                    g["weightage"],
                    progress.get(g["id"], 0.0),
                ]
            )
    return buf.getvalue()

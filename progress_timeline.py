"""Small overall progress timeline chart (all goals combined)."""

from __future__ import annotations

import calendar
import io
from collections import defaultdict
from datetime import date, datetime

import pandas as pd

from config import parse_month_key, pace_info, weighted_score
from data import fetch_progress_log_timeline


def _overall_pct(goals: list[dict], progress_by_id: dict[str, float]) -> float:
    earned, total_weight = weighted_score(goals, progress_by_id)
    return (earned / total_weight * 100.0) if total_weight > 0 else 0.0


def _parse_log_date(recorded_at: str) -> date:
    try:
        dt = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            return dt.astimezone().date()
        return dt.date()
    except ValueError:
        return date.today()


def _daily_scores_from_log(
    user_id: str,
    month_key: str,
    goals: list[dict],
) -> dict[date, float]:
    """Last overall score recorded on each calendar day (from progress log)."""
    goal_ids = {g["id"] for g in goals}
    state: dict[str, float] = {g["id"]: 0.0 for g in goals}
    daily: dict[date, float] = {}

    log_entries = fetch_progress_log_timeline(user_id, month_key)
    batches: dict[str, dict[str, float]] = defaultdict(dict)
    for entry in log_entries:
        gid = entry["goal_id"]
        if gid not in goal_ids:
            continue
        batches[entry["recorded_at"][:19]][gid] = entry["value"]

    parsed = parse_month_key(month_key)
    if not parsed:
        return daily
    year, month = parsed
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)

    for ts_key in sorted(batches.keys()):
        for gid, val in batches[ts_key].items():
            state[gid] = val
        d = _parse_log_date(ts_key)
        if d < month_start:
            d = month_start
        elif d > month_end:
            d = month_end
        daily[d] = _overall_pct(goals, state)

    return daily


def build_overall_timeline_df(
    user_id: str,
    month_key: str,
    goals: list[dict],
    current_progress: dict[str, float],
) -> tuple[pd.DataFrame, pd.DataFrame, set[date]]:
    """
    Return (achievement_df, benchmark_df, update_dates) for every day in the month.
    """
    parsed = parse_month_key(month_key)
    if not parsed:
        return pd.DataFrame(), pd.DataFrame(), set()

    year, month = parsed
    days_in_month = calendar.monthrange(year, month)[1]
    month_start = date(year, month, 1)
    month_end = date(year, month, days_in_month)
    today = date.today()
    current_score = _overall_pct(goals, current_progress)
    daily_updates = _daily_scores_from_log(user_id, month_key, goals)
    update_dates = set(daily_updates.keys())

    achievement_rows: list[dict] = []
    benchmark_rows: list[dict] = []
    carry = 0.0

    for day in range(1, days_in_month + 1):
        d = date(year, month, day)
        if d in daily_updates:
            carry = daily_updates[d]

        # Benchmark: linear pace 0% → 100% across full month
        benchmark_rows.append(
            {
                "date": d,
                "score": (day / days_in_month) * 100.0,
            }
        )

        # Achievement: forward-fill; today uses live form; future days hold today's score
        if month_start <= today <= month_end:
            if d < today:
                score = carry
            elif d == today:
                score = current_score
            else:
                score = current_score
        elif today > month_end:
            score = carry
        else:
            score = 0.0

        achievement_rows.append({"date": d, "score": score})

    achievement_df = pd.DataFrame(achievement_rows)
    achievement_df["date"] = pd.to_datetime(achievement_df["date"])

    benchmark_df = pd.DataFrame(benchmark_rows)
    benchmark_df["date"] = pd.to_datetime(benchmark_df["date"])

    return achievement_df, benchmark_df, update_dates


def _line_color_for_score(goals: list[dict], progress: dict[str, float], month_key: str) -> str:
    tone = pace_info(_overall_pct(goals, progress), month_key)["tone"]
    return {"ahead": "#22c55e", "behind": "#ef4444", "track": "#4f46e5"}[tone]


def render_timeline_png_bytes(
    user_id: str,
    month_key: str,
    goals: list[dict],
    current_progress: dict[str, float],
) -> bytes | None:
    """PNG chart for Telegram (matplotlib, no Streamlit)."""
    achievement_df, benchmark_df, update_dates = build_overall_timeline_df(
        user_id, month_key, goals, current_progress
    )
    if achievement_df.empty or benchmark_df.empty:
        return None

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    line_color = _line_color_for_score(goals, current_progress, month_key)
    parsed = parse_month_key(month_key)
    if not parsed:
        return None
    year, month = parsed
    days = calendar.monthrange(year, month)[1]

    today = date.today()
    marker_dates = set(update_dates)
    if date(year, month, 1) <= today <= date(year, month, days):
        marker_dates.add(today)

    fig, ax = plt.subplots(figsize=(7.2, 2.4), dpi=120)
    fig.patch.set_facecolor("#fafafa")
    ax.set_facecolor("#fafafa")

    ax.plot(
        benchmark_df["date"],
        benchmark_df["score"],
        color="#f97316",
        linestyle=(0, (5, 4)),
        linewidth=1.8,
        label="Benchmark",
    )
    ax.plot(
        achievement_df["date"],
        achievement_df["score"],
        color=line_color,
        linewidth=2.4,
        label="Your score",
    )

    if marker_dates:
        marks = achievement_df[
            achievement_df["date"].dt.date.isin(marker_dates)
        ]
        if not marks.empty:
            ax.scatter(
                marks["date"],
                marks["score"],
                color=line_color,
                s=28,
                zorder=5,
            )

    ax.set_ylim(0, 100)
    ax.set_yticks([0, 50, 100])
    ax.set_xlim(
        pd.Timestamp(year, month, 1),
        pd.Timestamp(year, month, days),
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days // 6)))
    ax.tick_params(axis="both", labelsize=8, colors="#6b7280")
    ax.grid(axis="y", color="#e5e7eb", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#e5e7eb")
    ax.spines["bottom"].set_color("#e5e7eb")
    ax.legend(loc="upper left", fontsize=7, frameon=False)

    plt.tight_layout(pad=0.6)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def render_overall_timeline(
    user_id: str,
    month_key: str,
    goals: list[dict],
    current_progress: dict[str, float],
) -> None:
    """Render a compact full-month overall score vs benchmark chart."""
    import altair as alt
    import streamlit as st

    achievement_df, benchmark_df, update_dates = build_overall_timeline_df(
        user_id, month_key, goals, current_progress
    )
    if achievement_df.empty:
        st.caption("Save progress to see your timeline.")
        return

    parsed = parse_month_key(month_key)
    year, month = parsed  # type: ignore[misc]
    days = calendar.monthrange(year, month)[1]
    x_scale = alt.Scale(
        domain=[pd.Timestamp(year, month, 1), pd.Timestamp(year, month, days)],
        nice=False,
    )

    # Markers only on days you actually saved progress (+ today)
    today = date.today()
    marker_dates = {pd.Timestamp(d) for d in update_dates}
    if parsed and date(year, month, 1) <= today <= date(year, month, days):
        marker_dates.add(pd.Timestamp(today))

    markers_df = achievement_df[achievement_df["date"].isin(marker_dates)]

    overall_pct = _overall_pct(goals, current_progress)
    line_color = _line_color_for_score(goals, current_progress, month_key)

    benchmark_line = (
        alt.Chart(benchmark_df)
        .mark_line(strokeDash=[5, 4], color="#f97316", strokeWidth=1.5)
        .encode(
            x=alt.X("date:T", scale=x_scale),
            y=alt.Y("score:Q", scale=alt.Scale(domain=[0, 100])),
        )
    )

    achievement_line = (
        alt.Chart(achievement_df)
        .mark_line(color=line_color, interpolate="monotone", strokeWidth=2.5)
        .encode(
            x=alt.X(
                "date:T",
                title=None,
                scale=x_scale,
                axis=alt.Axis(
                    format="%d %b",
                    labelAngle=0,
                    tickCount=min(6, days),
                    grid=False,
                    domainColor="#e5e7eb",
                    labelColor="#6b7280",
                    labelFontSize=10,
                ),
            ),
            y=alt.Y(
                "score:Q",
                title=None,
                scale=alt.Scale(domain=[0, 100]),
                axis=alt.Axis(
                    values=[0, 50, 100],
                    gridColor="#f3f4f6",
                    domain=False,
                    labelColor="#9ca3af",
                    labelFontSize=10,
                ),
            ),
        )
    )

    achievement_pts = (
        alt.Chart(markers_df)
        .mark_circle(color=line_color, size=40)
        .encode(x="date:T", y="score:Q")
    )

    chart = (
        alt.layer(benchmark_line, achievement_line, achievement_pts)
        .properties(height=100, padding={"left": 4, "right": 8, "top": 4, "bottom": 0})
    )

    st.altair_chart(chart, use_container_width=True)
    tone = pace_info(overall_pct, month_key)["tone"]
    color_word = {"ahead": "Green", "behind": "Red", "track": "Blue"}[tone]
    st.caption(
        f"{color_word} line — your overall score · "
        f"Orange dashed — expected pace (full month)"
    )

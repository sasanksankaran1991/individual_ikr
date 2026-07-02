"""Admin tab: reminder settings, status, export, and backup."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import DEFAULT_TIMEZONE, current_month_key, format_month_label
from export_utils import export_all_users_csv, export_month_csv, read_database_bytes
from notifications import broadcast_summaries_to_all_users
from reminder_settings import (
    COMMON_TIMEZONES,
    MAX_EDIT_GRACE_DAY,
    MAX_POLL_INTERVAL,
    MIN_EDIT_GRACE_DAY,
    MIN_POLL_INTERVAL,
    get_reminder_settings,
    save_reminder_settings,
)
from scheduler_status import get_scheduler_status
from session_auth import current_user_id
from styles import card_container

_ADMIN_WIDGET_KEYS = (
    "admin_reminders_enabled",
    "admin_evening_enabled",
    "admin_mid_month",
    "admin_end_month",
    "admin_reminder_hour",
    "admin_reminder_minute",
    "admin_evening_hour",
    "admin_evening_minute",
    "admin_timezone",
    "admin_poll_interval",
    "admin_session_timeout",
    "admin_allow_unequal",
    "admin_config_grace",
    "admin_progress_grace",
)


def _clear_admin_widget_state() -> None:
    for key in _ADMIN_WIDGET_KEYS:
        st.session_state.pop(key, None)


def _init_settings_widgets(settings: dict) -> None:
    """Seed widget keys once per load (never overwrite after widgets exist)."""
    defaults = {
        "admin_reminders_enabled": settings["reminders_enabled"],
        "admin_evening_enabled": settings["evening_nudge_enabled"],
        "admin_mid_month": settings["mid_month_enabled"],
        "admin_end_month": settings["end_month_enabled"],
        "admin_reminder_hour": int(settings["reminder_hour"]),
        "admin_reminder_minute": int(settings["reminder_minute"]),
        "admin_evening_hour": int(settings["evening_nudge_hour"]),
        "admin_evening_minute": int(settings["evening_nudge_minute"]),
        "admin_poll_interval": int(settings["poll_interval_seconds"]),
        "admin_session_timeout": int(settings["session_timeout_minutes"]),
        "admin_allow_unequal": settings["allow_unequal_weightage"],
        "admin_config_grace": int(settings["config_edit_grace_day"]),
        "admin_progress_grace": int(settings["progress_edit_grace_day"]),
    }
    tz_options = COMMON_TIMEZONES + (
        [settings["timezone"]] if settings["timezone"] not in COMMON_TIMEZONES else []
    )
    tz = settings["timezone"]
    defaults["admin_timezone"] = tz if tz in tz_options else tz_options[0]

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


@st.cache_data(ttl=60, show_spinner=False)
def _cached_scheduler_status() -> dict:
    return get_scheduler_status()


def _render_settings_form(settings: dict) -> None:
    _init_settings_widgets(settings)

    enabled = st.toggle("Send daily reminders", key="admin_reminders_enabled")
    evening = st.toggle("Evening nudge (if no update today)", key="admin_evening_enabled")
    mid_month = st.toggle("Mid-month report (15th)", key="admin_mid_month")
    end_month = st.toggle("Month-end summary (last day)", key="admin_end_month")

    c1, c2 = st.columns(2)
    with c1:
        hour = st.number_input("Morning hour", 0, 23, key="admin_reminder_hour")
        ev_hour = st.number_input("Evening hour", 0, 23, key="admin_evening_hour")
    with c2:
        minute = st.number_input("Morning minute", 0, 59, key="admin_reminder_minute")
        ev_min = st.number_input("Evening minute", 0, 59, key="admin_evening_minute")

    tz_options = COMMON_TIMEZONES + (
        [settings["timezone"]] if settings["timezone"] not in COMMON_TIMEZONES else []
    )
    st.selectbox(
        "Timezone",
        options=tz_options,
        format_func=lambda x: DEFAULT_TIMEZONE if not x else x,
        help="Used for Cloud Scheduler reminder times (default Asia/Kolkata).",
        key="admin_timezone",
    )

    st.markdown("Cloud: Telegram is polled every **15 minutes** via Google Cloud Scheduler.")
    st.number_input(
        "Telegram poll interval when app is open (seconds)",
        MIN_POLL_INTERVAL,
        MAX_POLL_INTERVAL,
        step=10,
        help="Only applies while someone has the Streamlit app open.",
        key="admin_poll_interval",
    )
    st.number_input(
        "Session timeout (minutes)",
        5,
        10080,
        step=60,
        help="Default is 7200 (5 days). Persistent login cookie also lasts 5 days.",
        key="admin_session_timeout",
    )
    st.toggle(
        "Allow saving goals when weightage ≠ 100",
        key="admin_allow_unequal",
    )

    st.divider()
    st.markdown("**Month edit windows**")
    st.caption(
        "How many days into the *next* month users may still edit a closed month. "
        "Example: grace **15** → May goals editable through 15 June."
    )
    g1, g2 = st.columns(2)
    with g1:
        st.number_input(
            "Goal config grace (day of next month)",
            MIN_EDIT_GRACE_DAY,
            MAX_EDIT_GRACE_DAY,
            help="Create or change goals for the previous month.",
            key="admin_config_grace",
        )
    with g2:
        st.number_input(
            "Progress grace (day of next month)",
            MIN_EDIT_GRACE_DAY,
            MAX_EDIT_GRACE_DAY,
            help="Update progress / daily log for the previous month.",
            key="admin_progress_grace",
        )

    if st.button("Save settings", type="primary", use_container_width=True, key="admin_save_settings"):
        ok, message = save_reminder_settings(
            reminder_hour=int(hour),
            reminder_minute=int(minute),
            poll_interval_seconds=int(st.session_state["admin_poll_interval"]),
            reminders_enabled=enabled,
            timezone=str(st.session_state["admin_timezone"]),
            evening_nudge_enabled=evening,
            evening_nudge_hour=int(ev_hour),
            evening_nudge_minute=int(ev_min),
            mid_month_enabled=mid_month,
            end_month_enabled=end_month,
            session_timeout_minutes=int(st.session_state["admin_session_timeout"]),
            allow_unequal_weightage=bool(st.session_state["admin_allow_unequal"]),
            config_edit_grace_day=int(st.session_state["admin_config_grace"]),
            progress_edit_grace_day=int(st.session_state["admin_progress_grace"]),
        )
        if ok:
            _cached_scheduler_status.clear()
            _clear_admin_widget_state()
            st.session_state["admin_settings_revision"] = (
                int(st.session_state.get("admin_settings_revision", 0)) + 1
            )
            st.success(message)
            st.rerun()
        else:
            st.error(message)


def render_settings_content() -> None:
    """Settings cards — used inside the unified Account tab (admin)."""
    try:
        status = _cached_scheduler_status()
    except Exception as exc:
        st.warning(f"Could not load system status: {exc}")
        status = {
            "telegram_configured": False,
            "telegram_user_count": 0,
            "last_poll_at": "Unknown",
            "last_daily_reminder_date": "Unknown",
            "next_daily_reminder": "Unknown",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }

    with card_container():
        st.markdown("#### System status")
        s1, s2 = st.columns(2)
        s1.metric("Telegram", "OK" if status["telegram_configured"] else "Missing token")
        s2.metric("Telegram users", status["telegram_user_count"])
        if status.get("bot_username"):
            st.caption(f"Bot: @{status['bot_username']}")
        st.caption(f"Last poll: {status['last_poll_at']}")
        st.caption(f"Telegram (cloud): every 15 min ({status.get('timezone', 'Asia/Kolkata')})")
        st.caption(f"Morning reminder: {status.get('morning_reminder_at', '?')}")
        st.caption(
            f"Evening nudge: {status.get('evening_nudge_at', '?')} "
            f"({'on' if status.get('evening_nudge_enabled') else 'paused'})"
        )
        st.caption(f"Cloud scheduler sync: {status.get('cloud_scheduler_sync_at', 'Never')}")
        if status.get("cloud_scheduler_sync_error"):
            st.warning(f"Scheduler sync error: {status['cloud_scheduler_sync_error']}")
        schedulers = status.get("cloud_schedulers") or []
        if schedulers:
            for row in schedulers:
                st.caption(
                    f"  {row['id']}: {row['state']} — {row['cron']}"
                )
        if status.get("last_telegram_error"):
            st.warning(f"Last Telegram error: {status['last_telegram_error']}")
        st.caption(f"Last daily reminder date: {status['last_daily_reminder_date']}")
        st.caption(f"Checked at: {status['checked_at']}")

    with card_container():
        st.markdown("#### Load diagnostics")
        st.caption(
            "Shows what takes time when the app loads. "
            "History is usually slowest when many months need live scoring."
        )
        last = st.session_state.get("_ikr_page_timings") or {}
        if last:
            st.markdown("**Last page render**")
            for label, ms in last.items():
                st.write(f"- {label}: **{ms:.0f} ms**")

        if st.button("Run load benchmark", key="admin_run_load_benchmark", use_container_width=True):
            from load_profile import benchmark_user_load

            uid = current_user_id()
            with st.spinner("Measuring…"):
                rows = benchmark_user_load(uid)
            st.session_state["_ikr_benchmark_rows"] = rows

        bench = st.session_state.get("_ikr_benchmark_rows")
        if bench:
            st.markdown("**Benchmark results** (newest run)")
            table_rows = [
                {"Step": r.label, "Time (ms)": f"{r.ms:.1f}", "Notes": r.detail} for r in bench
            ]
            st.dataframe(table_rows, use_container_width=True, hide_index=True)
            slowest = max(bench, key=lambda r: r.ms)
            st.info(
                f"Slowest step: **{slowest.label}** ({slowest.ms:.0f} ms). "
                f"{slowest.detail}"
            )

    settings = get_reminder_settings()
    revision = int(st.session_state.get("admin_settings_revision", 0))
    loaded_revision = st.session_state.get("admin_settings_loaded_revision")
    if loaded_revision != revision:
        _clear_admin_widget_state()
        st.session_state["admin_settings_loaded_revision"] = revision

    with card_container():
        st.markdown("#### Reminders & polling")
        _render_settings_form(settings)

    with card_container():
        st.markdown("#### Backup & export")
        db_bytes = read_database_bytes()
        if db_bytes:
            stamp = datetime.now().strftime("%Y%m%d")
            st.download_button(
                "Download database backup (ikr.db)",
                data=db_bytes,
                file_name=f"ikr_backup_{stamp}.db",
                mime="application/octet-stream",
                use_container_width=True,
                key="admin_download_db",
            )

        uid = current_user_id()
        mk = current_month_key()
        st.download_button(
            f"Export my {format_month_label(mk)} (CSV)",
            data=export_month_csv(uid, mk),
            file_name=f"ikr_{mk}.csv",
            mime="text/csv",
            use_container_width=True,
            key="admin_export_month",
        )
        st.download_button(
            "Export all users current month (CSV)",
            data=export_all_users_csv(),
            file_name=f"ikr_all_{mk}.csv",
            mime="text/csv",
            use_container_width=True,
            key="admin_export_all",
        )

        if st.button(
            "Send Telegram summary to all users now",
            use_container_width=True,
            key="admin_broadcast_summary",
        ):
            results = broadcast_summaries_to_all_users()
            for r in results:
                st.write(f"**{r['user']}**: {r['status']} — {r.get('detail', '')}")


def render_settings_tab() -> None:
    """Standalone settings page (legacy entry point)."""
    st.markdown("### Settings")
    st.caption("Reminders, system status, backup, and export.")
    render_settings_content()

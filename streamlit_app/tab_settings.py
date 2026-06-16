"""Admin tab: reminder settings, status, export, and backup."""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from config import current_month_key, format_month_label
from export_utils import export_all_users_csv, export_month_csv, read_database_bytes
from notifications import broadcast_summaries_to_all_users
from reminder_settings import (
    COMMON_TIMEZONES,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    get_reminder_settings,
    save_reminder_settings,
)
from scheduler_status import get_scheduler_status
from session_auth import current_user_id
from styles import card_container


def render_settings_tab() -> None:
    st.markdown("### Settings")
    st.caption("Admin: reminders, system status, backup, and export.")

    status = get_scheduler_status()

    with card_container():
        st.markdown("#### System status")
        s1, s2 = st.columns(2)
        s1.metric("Telegram", "OK" if status["telegram_configured"] else "Missing token")
        s2.metric("Telegram users", status["telegram_user_count"])
        if status.get("bot_username"):
            st.caption(f"Bot: @{status['bot_username']}")
        st.caption(f"Last poll: {status['last_poll_at']}")
        if status.get("last_telegram_error"):
            st.warning(f"Last Telegram error: {status['last_telegram_error']}")
        st.caption(f"Last daily reminder date: {status['last_daily_reminder_date']}")
        st.caption(f"Next daily reminder: {status['next_daily_reminder']}")
        st.caption(f"Checked at: {status['checked_at']}")

    settings = get_reminder_settings()

    with card_container():
        st.markdown("#### Reminders & polling")
        enabled = st.toggle(
            "Send daily reminders",
            value=settings["reminders_enabled"],
            key="settings_reminders_enabled",
        )
        evening = st.toggle(
            "Evening nudge (if no update today)",
            value=settings["evening_nudge_enabled"],
            key="settings_evening_enabled",
        )
        mid_month = st.toggle("Mid-month report (15th)", value=settings["mid_month_enabled"])
        end_month = st.toggle("Month-end summary (last day)", value=settings["end_month_enabled"])

        c1, c2 = st.columns(2)
        with c1:
            hour = st.number_input("Morning hour", 0, 23, int(settings["reminder_hour"]))
            ev_hour = st.number_input("Evening hour", 0, 23, int(settings["evening_nudge_hour"]))
        with c2:
            minute = st.number_input("Morning minute", 0, 59, int(settings["reminder_minute"]))
            ev_min = st.number_input("Evening minute", 0, 59, int(settings["evening_nudge_minute"]))

        tz_options = COMMON_TIMEZONES + (
            [settings["timezone"]] if settings["timezone"] not in COMMON_TIMEZONES else []
        )
        tz_index = tz_options.index(settings["timezone"]) if settings["timezone"] in tz_options else 0
        timezone = st.selectbox(
            "Timezone (empty = server local)",
            options=tz_options,
            index=tz_index,
            format_func=lambda x: "Server local" if not x else x,
        )

        poll_interval = st.number_input(
            "Telegram poll interval (sec)",
            MIN_POLL_INTERVAL,
            MAX_POLL_INTERVAL,
            int(settings["poll_interval_seconds"]),
            step=10,
        )
        session_timeout = st.number_input(
            "Session timeout (minutes)",
            5,
            1440,
            int(settings["session_timeout_minutes"]),
            step=15,
        )
        allow_unequal = st.toggle(
            "Allow saving goals when weightage ≠ 100",
            value=settings["allow_unequal_weightage"],
        )

        if st.button("Save settings", type="primary", use_container_width=True):
            ok, message = save_reminder_settings(
                reminder_hour=int(hour),
                reminder_minute=int(minute),
                poll_interval_seconds=int(poll_interval),
                reminders_enabled=enabled,
                timezone=timezone,
                evening_nudge_enabled=evening,
                evening_nudge_hour=int(ev_hour),
                evening_nudge_minute=int(ev_min),
                mid_month_enabled=mid_month,
                end_month_enabled=end_month,
                session_timeout_minutes=int(session_timeout),
                allow_unequal_weightage=allow_unequal,
            )
            if ok:
                st.success(message)
                st.rerun()
            else:
                st.error(message)

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
            )

        uid = current_user_id()
        mk = current_month_key()
        st.download_button(
            f"Export my {format_month_label(mk)} (CSV)",
            data=export_month_csv(uid, mk),
            file_name=f"ikr_{mk}.csv",
            mime="text/csv",
            use_container_width=True,
        )
        st.download_button(
            "Export all users current month (CSV)",
            data=export_all_users_csv(),
            file_name=f"ikr_all_{mk}.csv",
            mime="text/csv",
            use_container_width=True,
        )

        if st.button("Send Telegram summary to all users now", use_container_width=True):
            results = broadcast_summaries_to_all_users()
            for r in results:
                st.write(f"**{r['user']}**: {r['status']} — {r.get('detail', '')}")

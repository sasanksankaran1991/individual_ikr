"""Admin tab: reminder and Telegram poll settings."""

from __future__ import annotations

import streamlit as st

from reminder_settings import (
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    get_reminder_settings,
    save_reminder_settings,
)
from styles import card_container


def render_settings_tab() -> None:
    st.markdown("### Reminder settings")
    st.caption(
        "Configure in-app Telegram polling and daily reminder time. "
        "Uses your computer's local clock. The Streamlit app must be running "
        "for reminders to send."
    )

    settings = get_reminder_settings()

    with card_container():
        st.markdown("#### Daily Telegram reminders")
        enabled = st.toggle(
            "Send daily reminders",
            value=settings["reminders_enabled"],
            help="When off, inbound Telegram messages are still processed.",
            key="settings_reminders_enabled",
        )

        time_col1, time_col2 = st.columns(2)
        with time_col1:
            hour = st.number_input(
                "Hour (24h)",
                min_value=0,
                max_value=23,
                value=int(settings["reminder_hour"]),
                step=1,
                key="settings_reminder_hour",
            )
        with time_col2:
            minute = st.number_input(
                "Minute",
                min_value=0,
                max_value=59,
                value=int(settings["reminder_minute"]),
                step=1,
                key="settings_reminder_minute",
            )

        st.caption(
            f"Reminders fire once per day between **{hour:02d}:{minute:02d}** "
            f"and **{hour:02d}:59** (local time)."
        )

    with card_container():
        st.markdown("#### Telegram polling")
        poll_interval = st.number_input(
            "Poll interval (seconds)",
            min_value=MIN_POLL_INTERVAL,
            max_value=MAX_POLL_INTERVAL,
            value=int(settings["poll_interval_seconds"]),
            step=10,
            help="How often the app checks Telegram for replies while Streamlit is open.",
            key="settings_poll_interval",
        )
        st.caption(
            f"Telegram is checked about every **{poll_interval}** seconds. "
            "Lower values respond faster but use slightly more network."
        )

    if st.button("Save settings", type="primary", key="settings_save_btn", use_container_width=True):
        ok, message = save_reminder_settings(
            reminder_hour=int(hour),
            reminder_minute=int(minute),
            poll_interval_seconds=int(poll_interval),
            reminders_enabled=enabled,
        )
        if ok:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

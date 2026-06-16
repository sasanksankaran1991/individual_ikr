"""
Individual IKR dashboard — monthly personal development goals.

Run from repo root (opens on port 18501):

  streamlit run streamlit_app/app.py

  # Or explicitly:
  streamlit run streamlit_app/app.py --server.port=18501
"""

from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

import streamlit as st

from config import STREAMLIT_MIN_POLL_INTERVAL_SECONDS
from data import init_db
from reminder_settings import get_reminder_settings
from session_auth import (
    bootstrap_cookies,
    check_session_valid,
    current_user_is_admin,
    current_username,
    get_cookie_manager,
    is_logged_in,
    logout,
    persist_login_cookie,
    try_restore_session_from_cookie,
)
from pwa import inject_pwa
from styles import inject_styles
from tab_account import render_account_tab
from tab_config import render_config_tab
from tab_history import render_history_tab
from tab_login import render_login_page
from tab_progress import render_progress_tab
from tab_settings import render_settings_tab
from tab_users import render_users_tab


def _background_tick() -> None:
    from streamlit_scheduler import schedule_background_tick

    settings = get_reminder_settings()
    interval = max(
        STREAMLIT_MIN_POLL_INTERVAL_SECONDS,
        int(settings["poll_interval_seconds"]),
    )
    schedule_background_tick(interval)


def _register_background_scheduler() -> None:
    """Poll Telegram on a background thread so the UI stays responsive."""
    settings = get_reminder_settings()
    interval = max(
        STREAMLIT_MIN_POLL_INTERVAL_SECONDS,
        int(settings["poll_interval_seconds"]),
    )
    try:
        st.fragment(run_every=timedelta(seconds=interval))(_background_tick)()
    except TypeError:
        now = time.time()
        last = float(st.session_state.get("_bg_scheduler_ts", 0))
        if now - last >= interval:
            st.session_state._bg_scheduler_ts = now
            _background_tick()


def main() -> None:
    st.set_page_config(
        page_title="Individual IKR",
        page_icon="🎯",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_db()
    inject_styles()
    inject_pwa()
    _register_background_scheduler()

    cookie_manager = get_cookie_manager()
    bootstrap_cookies(cookie_manager)

    if not is_logged_in():
        try_restore_session_from_cookie(cookie_manager)

    if persist_login_cookie(cookie_manager):
        st.rerun()

    if is_logged_in() and not check_session_valid():
        st.warning("Session expired. Please sign in again.")
        logout(cookie_manager)
        render_login_page()
        return

    if not is_logged_in():
        render_login_page()
        return

    if not st.session_state.get("_tg_boot_polled"):
        st.session_state._tg_boot_polled = True
        from streamlit_scheduler import schedule_background_tick

        schedule_background_tick(0, force=True)

    head_l, head_r = st.columns([5, 1])
    with head_l:
        st.markdown("## Individual IKR")
        role = " · Admin" if current_user_is_admin() else ""
        st.caption(f"Signed in as **{current_username()}**{role}")
    with head_r:
        if st.button("Sign out", key="sign_out_btn", use_container_width=True):
            logout(cookie_manager)
            st.rerun()

    tab_names = ["Progress", "Config", "History", "Account"]
    if current_user_is_admin():
        tab_names.extend(["Settings", "Users"])

    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_progress_tab()

    with tabs[1]:
        render_config_tab()

    with tabs[2]:
        render_history_tab()

    with tabs[3]:
        render_account_tab()

    if current_user_is_admin() and len(tabs) > 4:
        with tabs[4]:
            render_settings_tab()
        with tabs[5]:
            render_users_tab()


if __name__ == "__main__":
    main()

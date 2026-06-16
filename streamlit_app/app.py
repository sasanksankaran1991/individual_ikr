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

from data import init_db
from reminder_settings import get_reminder_settings
from session_auth import (
    check_session_valid,
    current_user_is_admin,
    current_username,
    is_logged_in,
    logout,
)
from pwa import inject_pwa
from styles import inject_styles
from tab_account import render_account_tab
from tab_config import render_config_tab
from tab_login import render_login_page
from tab_progress import render_progress_tab
from tab_settings import render_settings_tab
from tab_users import render_users_tab


def _background_tick() -> None:
    from background_scheduler import run_background_tick

    run_background_tick()


def _register_background_scheduler() -> None:
    """Poll Telegram and send daily reminders using admin-configured intervals."""
    settings = get_reminder_settings()
    interval = max(30, int(settings["poll_interval_seconds"]))
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

    if is_logged_in() and not check_session_valid():
        st.warning("Session expired. Please sign in again.")
        render_login_page()
        return

    if not is_logged_in():
        render_login_page()
        return

    head_l, head_r = st.columns([5, 1])
    with head_l:
        st.markdown("## Individual IKR")
        role = " · Admin" if current_user_is_admin() else ""
        st.caption(f"Signed in as **{current_username()}**{role}")
    with head_r:
        if st.button("Sign out", key="sign_out_btn", use_container_width=True):
            logout()
            st.rerun()

    tab_names = ["Progress", "Config", "Account"]
    if current_user_is_admin():
        tab_names.extend(["Settings", "Users"])

    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_progress_tab()

    with tabs[1]:
        render_config_tab()

    with tabs[2]:
        render_account_tab()

    if current_user_is_admin() and len(tabs) > 3:
        with tabs[3]:
            render_settings_tab()
        with tabs[4]:
            render_users_tab()


if __name__ == "__main__":
    main()

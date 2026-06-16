"""
Individual IKR dashboard — monthly personal development goals.

Run from repo root:

  streamlit run streamlit_app/app.py
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
from session_auth import (
    current_user_is_admin,
    current_username,
    is_logged_in,
    logout,
)
from styles import inject_styles
from tab_account import render_account_tab
from tab_config import render_config_tab
from tab_login import render_login_page
from tab_progress import render_progress_tab
from tab_users import render_users_tab


def _poll_telegram_inbound() -> None:
    """Pick up Telegram replies (progress updates) without user opening a specific tab."""
    from telegram_inbound import process_all_inbound_updates

    now = time.time()
    last = float(st.session_state.get("_tg_inbound_poll_ts", 0))
    if now - last < 20:
        return
    st.session_state._tg_inbound_poll_ts = now
    process_all_inbound_updates()


def _telegram_background_poll() -> None:
    _poll_telegram_inbound()


def main() -> None:
    st.set_page_config(
        page_title="Individual IKR",
        page_icon="🎯",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_db()
    inject_styles()

    if not is_logged_in():
        render_login_page()
        return

    _poll_telegram_inbound()
    try:
        st.fragment(run_every=timedelta(seconds=30))(_telegram_background_poll)()
    except TypeError:
        pass

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
        tab_names.append("Users")

    tabs = st.tabs(tab_names)

    with tabs[0]:
        render_progress_tab()

    with tabs[1]:
        render_config_tab()

    with tabs[2]:
        render_account_tab()

    if current_user_is_admin() and len(tabs) > 3:
        with tabs[3]:
            render_users_tab()


if __name__ == "__main__":
    main()

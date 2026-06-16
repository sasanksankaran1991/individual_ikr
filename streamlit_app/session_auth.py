"""Streamlit session helpers for authenticated users."""

from __future__ import annotations

import time

import streamlit as st

SESSION_USER_ID = "auth_user_id"
SESSION_USERNAME = "auth_username"
SESSION_IS_ADMIN = "auth_is_admin"
SESSION_LOGIN_AT = "auth_login_at"


def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_USER_ID))


def check_session_valid() -> bool:
    """Return False and log out if session exceeded timeout."""
    if not is_logged_in():
        return False
    from reminder_settings import get_session_timeout_minutes

    timeout_sec = get_session_timeout_minutes() * 60
    login_at = float(st.session_state.get(SESSION_LOGIN_AT, 0))
    if login_at and time.time() - login_at > timeout_sec:
        logout()
        return False
    return True


def current_user_id() -> str:
    user_id = st.session_state.get(SESSION_USER_ID)
    if not user_id:
        raise RuntimeError("No authenticated user in session.")
    return str(user_id)


def current_username() -> str:
    return str(st.session_state.get(SESSION_USERNAME, ""))


def current_user_is_admin() -> bool:
    return bool(st.session_state.get(SESSION_IS_ADMIN))


def login(user: dict) -> None:
    st.session_state[SESSION_USER_ID] = user["id"]
    st.session_state[SESSION_USERNAME] = user["username"]
    st.session_state[SESSION_IS_ADMIN] = user["is_admin"]
    st.session_state[SESSION_LOGIN_AT] = time.time()


def logout() -> None:
    for key in (SESSION_USER_ID, SESSION_USERNAME, SESSION_IS_ADMIN, SESSION_LOGIN_AT):
        if key in st.session_state:
            del st.session_state[key]
    _clear_user_scoped_widget_state()


def _clear_user_scoped_widget_state() -> None:
    prefixes = ("cfg_", "config_rows_", "progress_", "config_")
    for key in list(st.session_state.keys()):
        if isinstance(key, str) and key.startswith(prefixes):
            del st.session_state[key]
    if "config_active_month" in st.session_state:
        del st.session_state["config_active_month"]
    if "config_active_user" in st.session_state:
        del st.session_state["config_active_user"]

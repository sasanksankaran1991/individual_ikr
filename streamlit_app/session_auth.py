"""Streamlit session helpers for authenticated users."""

from __future__ import annotations

import streamlit as st

SESSION_USER_ID = "auth_user_id"
SESSION_USERNAME = "auth_username"
SESSION_IS_ADMIN = "auth_is_admin"


def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_USER_ID))


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


def logout() -> None:
    for key in (SESSION_USER_ID, SESSION_USERNAME, SESSION_IS_ADMIN):
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

"""Streamlit session helpers for authenticated users."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

import streamlit as st

from config import AUTH_SESSION_COOKIE, AUTH_SESSION_DAYS

SESSION_USER_ID = "auth_user_id"
SESSION_USERNAME = "auth_username"
SESSION_IS_ADMIN = "auth_is_admin"
SESSION_LOGIN_AT = "auth_login_at"
SESSION_TOKEN = "auth_session_token"
PENDING_COOKIE_TOKEN = "_pending_auth_cookie"
COOKIE_MANAGER = "_ikr_cookie_manager"
COOKIE_BOOTSTRAP = "_ikr_cookie_bootstrap"


def get_cookie_manager():
    """One CookieManager per Streamlit session (cannot use @st.cache_resource)."""
    import extra_streamlit_components as stx

    if COOKIE_MANAGER not in st.session_state:
        st.session_state[COOKIE_MANAGER] = stx.CookieManager(key="ikr_cookie_manager")
    return st.session_state[COOKIE_MANAGER]


def bootstrap_cookies(cookie_manager) -> None:
    """Load browser cookies; rerun once so the component can sync after refresh."""
    if is_logged_in():
        return

    phase = int(st.session_state.get(COOKIE_BOOTSTRAP, 0))
    cookie_manager.get_all(key="ikr_cookie_bootstrap")
    st.session_state[COOKIE_BOOTSTRAP] = phase + 1

    if phase < 1:
        st.rerun()


def is_logged_in() -> bool:
    return bool(st.session_state.get(SESSION_USER_ID))


def check_session_valid() -> bool:
    """Return False and log out if session exceeded timeout."""
    if not is_logged_in():
        return False

    token = st.session_state.get(SESSION_TOKEN)
    if token:
        from auth import user_from_auth_session

        user = user_from_auth_session(str(token))
        if not user:
            logout()
            return False
        return True

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


def _apply_user_session(user: dict, *, token: str | None = None) -> None:
    st.session_state[SESSION_USER_ID] = user["id"]
    st.session_state[SESSION_USERNAME] = user["username"]
    st.session_state[SESSION_IS_ADMIN] = user["is_admin"]
    st.session_state[SESSION_LOGIN_AT] = time.time()
    if token:
        st.session_state[SESSION_TOKEN] = token


def login(user: dict, *, remember: bool = True) -> None:
    token = None
    if remember:
        from auth import create_auth_session

        token = create_auth_session(user["id"], days=AUTH_SESSION_DAYS)
        st.session_state[PENDING_COOKIE_TOKEN] = token
    _apply_user_session(user, token=token)


def persist_login_cookie(cookie_manager) -> bool:
    """Write the auth cookie after login. Returns True if a rerun is needed."""
    token = st.session_state.get(PENDING_COOKIE_TOKEN)
    if not token:
        return False

    cookie_manager.set(
        AUTH_SESSION_COOKIE,
        token,
        key="ikr_auth_cookie_set",
        expires_at=datetime.now() + timedelta(days=AUTH_SESSION_DAYS),
        max_age=AUTH_SESSION_DAYS * 24 * 60 * 60,
        same_site="lax",
    )
    st.session_state.pop(PENDING_COOKIE_TOKEN, None)
    return True


def try_restore_session_from_cookie(cookie_manager) -> bool:
    """Restore login from browser cookie after a page refresh."""
    if is_logged_in():
        return True

    token = cookie_manager.get(AUTH_SESSION_COOKIE)
    if not token:
        return False

    from auth import user_from_auth_session

    user = user_from_auth_session(str(token))
    if not user:
        cookie_manager.delete(AUTH_SESSION_COOKIE, key="ikr_auth_cookie_delete")
        return False

    _apply_user_session(user, token=str(token))
    return True


def logout(cookie_manager=None) -> None:
    token = st.session_state.get(SESSION_TOKEN)
    if token:
        from auth import revoke_auth_session

        revoke_auth_session(str(token))

    if cookie_manager is None:
        try:
            cookie_manager = get_cookie_manager()
        except Exception:
            cookie_manager = None

    if cookie_manager is not None:
        try:
            cookie_manager.delete(AUTH_SESSION_COOKIE, key="ikr_auth_cookie_delete")
        except Exception:
            pass

    for key in (
        SESSION_USER_ID,
        SESSION_USERNAME,
        SESSION_IS_ADMIN,
        SESSION_LOGIN_AT,
        SESSION_TOKEN,
        PENDING_COOKIE_TOKEN,
        COOKIE_BOOTSTRAP,
    ):
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

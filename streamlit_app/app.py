"""
Individual IKR dashboard — monthly personal development goals.

Run from repo root (opens on port 18501):

  streamlit run streamlit_app/app.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent.parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


def _hot_reload_modules() -> None:
    """Reload cached modules in dev only (set IKR_DEV_RELOAD=1)."""
    if os.environ.get("IKR_DEV_RELOAD", "").lower() not in ("1", "true", "yes"):
        return
    import importlib

    def reload(name: str) -> None:
        mod = sys.modules.get(name)
        if mod is not None:
            importlib.reload(mod)

    for stem in (
        "config",
        "goal_scoring",
        "data",
        "reminder_settings",
        "notifications",
        "telegram_inbound",
        "background_scheduler",
        "scheduler_status",
        "month_history",
        "load_profile",
    ):
        reload(stem)


_hot_reload_modules()

import streamlit as st
import streamlit.components.v1 as components

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
from tab_login import render_login_page

_TAB_KEY = "ikr_active_tab"
_ADMIN_VIEW_KEY = "ikr_admin_view"
_VIEW_GEN_KEY = "ikr_view_gen"
_TAB_NAMES = ["Progress", "Config", "History", "Account"]


def _render_tab_content(active: str) -> None:
    """Import only the active tab (avoids loading Altair/pandas on every rerun)."""
    if active == "Progress":
        from tab_progress import render_progress_tab

        render_progress_tab()
    elif active == "Config":
        from tab_config import render_config_tab

        render_config_tab()
    elif active == "History":
        from tab_history import render_history_tab

        render_history_tab()
    elif active == "Account":
        from tab_account import render_account_tab

        render_account_tab()
    else:
        st.error(f"Unknown tab: {active}")


def _bump_view_gen() -> None:
    st.session_state[_VIEW_GEN_KEY] = int(st.session_state.get(_VIEW_GEN_KEY, 0)) + 1


def _clear_admin_view() -> None:
    st.session_state.pop(_ADMIN_VIEW_KEY, None)


def _go_settings() -> None:
    _bump_view_gen()
    st.session_state[_TAB_KEY] = "Account"
    st.session_state[_ADMIN_VIEW_KEY] = "settings"


def _go_users() -> None:
    _bump_view_gen()
    st.session_state[_TAB_KEY] = "Account"
    st.session_state[_ADMIN_VIEW_KEY] = "users"


def _go_sign_out() -> None:
    logout(get_cookie_manager())
    _clear_admin_view()


def _normalize_tab_state() -> None:
    if st.session_state.get(_TAB_KEY) not in _TAB_NAMES:
        st.session_state[_TAB_KEY] = _TAB_NAMES[0]
    admin_view = st.session_state.get(_ADMIN_VIEW_KEY)
    if admin_view not in (None, "settings", "users"):
        _clear_admin_view()


def _register_background_scheduler() -> None:
    if os.environ.get("IKR_USE_CLOUD_SCHEDULER", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return
    if st.session_state.get("_scheduler_loop_started"):
        return
    settings = get_reminder_settings()
    interval = max(
        STREAMLIT_MIN_POLL_INTERVAL_SECONDS,
        int(settings["poll_interval_seconds"]),
    )
    from streamlit_scheduler import start_background_loop

    start_background_loop(interval)
    st.session_state["_scheduler_loop_started"] = True


def _effective_view(active_tab: str, admin_view: str | None) -> str:
    if admin_view == "settings":
        return "Settings"
    if admin_view == "users":
        return "Users"
    return active_tab


def _purge_stale_progress(view: str) -> None:
    """Remove faded Progress DOM when another view is active (Streamlit stale bleed)."""
    if view == "Progress":
        return
    safe_view = view.replace("\\", "\\\\").replace('"', '\\"')
    components.html(
        f"""
        <script>
        (function () {{
            const doc = window.parent.document;
            if (!doc) return;
            const VIEW = "{safe_view}";

            function isProgressStale(el) {{
                if (!el || el.getAttribute("data-stale") !== "true") return false;
                if (el.querySelector("#ikr-progress-marker")) return true;
                if (el.querySelector('[data-testid="stAltairChart"]')) return true;
                const text = (el.innerText || "").slice(0, 900);
                return (
                    text.indexOf("Save numeric progress") >= 0 ||
                    text.indexOf("Overall score") >= 0
                );
            }}

            function purge() {{
                if (VIEW === "Progress") return;
                doc.querySelectorAll('[data-stale="true"]').forEach(function (el) {{
                    if (isProgressStale(el)) el.remove();
                }});
            }}

            purge();
            const obs = new MutationObserver(purge);
            obs.observe(doc.body, {{ childList: true, subtree: true }});
            setTimeout(function () {{ obs.disconnect(); }}, 6000);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def _render_header_menu(*, is_admin: bool) -> None:
    popover_label = " "
    try:
        popover = st.popover(
            popover_label,
            icon=":material/more_vert:",
            use_container_width=True,
        )
    except TypeError:
        popover = st.popover("⋮", use_container_width=True)

    with popover:
        if is_admin:
            st.button(
                "Settings",
                key="menu_settings_btn",
                use_container_width=True,
                on_click=_go_settings,
            )
            st.button(
                "Users",
                key="menu_users_btn",
                use_container_width=True,
                on_click=_go_users,
            )
            st.divider()
        st.button(
            "Sign out",
            key="menu_sign_out_btn",
            use_container_width=True,
            on_click=_go_sign_out,
        )


def _render_tab_nav() -> str:
    _normalize_tab_state()
    admin_view = st.session_state.get(_ADMIN_VIEW_KEY)

    cols = st.columns(len(_TAB_NAMES))
    for name, col in zip(_TAB_NAMES, cols):
        with col:
            is_active = st.session_state[_TAB_KEY] == name or (
                name == "Account" and bool(admin_view)
            )
            if st.button(
                name,
                key=f"ikr_tab_btn_{name}",
                type="primary" if is_active else "secondary",
                use_container_width=True,
            ):
                st.session_state[_TAB_KEY] = name
                _clear_admin_view()
                _bump_view_gen()
                st.rerun()

    return st.session_state[_TAB_KEY]


def _render_main_content(active: str) -> None:
    admin_view = st.session_state.get(_ADMIN_VIEW_KEY)
    view = _effective_view(active, admin_view)
    view_gen = int(st.session_state.get(_VIEW_GEN_KEY, 0))

    st.markdown(
        f'<div id="ikr-active-view" data-view="{view}" aria-hidden="true" '
        f'style="display:none"></div>',
        unsafe_allow_html=True,
    )

    with st.container(key=f"ikr_main_{view_gen}_{view}"):
        if admin_view == "settings":
            from tab_settings import render_settings_content

            st.markdown("### Settings")
            st.caption("Reminders, system status, backup, and export.")
            try:
                render_settings_content()
            except Exception as exc:
                st.error(f"Could not load Settings: {exc}")
            return

        if admin_view == "users":
            from tab_users import render_users_content

            st.markdown("### User management")
            st.caption("Create accounts and manage access.")
            try:
                render_users_content()
            except Exception as exc:
                st.error(f"Could not load Users: {exc}")
            return

        try:
            _render_tab_content(active)
        except Exception as exc:
            st.error(f"Could not load **{active}**: {exc}")

    _purge_stale_progress(view)


def main() -> None:
    page_t0 = time.perf_counter()
    timings: dict[str, float] = {}

    st.set_page_config(
        page_title="Individual IKR",
        page_icon="🎯",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    init_db()
    timings["Startup (DB init)"] = (time.perf_counter() - page_t0) * 1000.0
    inject_styles()
    inject_pwa()

    cookie_manager = get_cookie_manager()
    bootstrap_cookies(cookie_manager)

    if not is_logged_in():
        try_restore_session_from_cookie(cookie_manager)

    if is_logged_in() and not check_session_valid():
        st.warning("Session expired. Please sign in again.")
        logout(cookie_manager)
        render_login_page()
        return

    if not is_logged_in():
        render_login_page()
        return

    auth_t0 = time.perf_counter()
    if not st.session_state.get("_tg_boot_polled"):
        st.session_state._tg_boot_polled = True
        from streamlit_scheduler import schedule_background_tick

        schedule_background_tick(0, force=True)

    _register_background_scheduler()
    timings["Auth + background scheduler"] = (time.perf_counter() - auth_t0) * 1000.0

    is_admin = current_user_is_admin()

    try:
        head_l, head_r = st.columns([8, 1], vertical_alignment="center")
    except TypeError:
        head_l, head_r = st.columns([8, 1])
    with head_l:
        st.markdown("## Individual IKR")
        st.caption(f"Signed in as **{current_username()}**")
    with head_r:
        _render_header_menu(is_admin=is_admin)

    active_tab = _render_tab_nav()
    admin_view = st.session_state.get(_ADMIN_VIEW_KEY)

    content_t0 = time.perf_counter()
    _render_main_content(active_tab)
    view = _effective_view(active_tab, admin_view)
    timings[f"Active view ({view})"] = (time.perf_counter() - content_t0) * 1000.0
    timings["Total (logged-in page)"] = (time.perf_counter() - page_t0) * 1000.0
    st.session_state["_ikr_page_timings"] = timings

    if persist_login_cookie(cookie_manager) and not st.session_state.get("_cookie_saved"):
        st.session_state["_cookie_saved"] = True
        st.rerun()


if __name__ == "__main__":
    main()

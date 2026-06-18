"""Login screen."""

from __future__ import annotations

import streamlit as st

from auth import authenticate
from pwa import render_mobile_install_hint
from session_auth import login


def render_login_page() -> None:
    st.markdown(
        '<div id="ikr-login-marker" aria-hidden="true" style="display:none"></div>',
        unsafe_allow_html=True,
    )
    st.markdown("## Individual IKR")
    st.caption("Sign in to manage your personal development goals.")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", autocomplete="username", key="login_username")
        password = st.text_input(
            "Password",
            type="password",
            autocomplete="current-password",
            key="login_password",
        )
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

    if submitted:
        user = authenticate(username, password)
        if user:
            login(user)
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.caption("Default admin: **admin** / **admin** (change after first login in Account).")
    render_mobile_install_hint()

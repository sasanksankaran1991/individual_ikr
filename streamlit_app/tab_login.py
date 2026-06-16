"""Login screen."""

from __future__ import annotations

import streamlit as st

from auth import authenticate
from session_auth import login


def render_login_page() -> None:
    st.markdown("## Individual IKR")
    st.caption("Sign in to manage your personal development goals.")

    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

    if submitted:
        user = authenticate(username, password)
        if user:
            login(user)
            st.rerun()
        else:
            st.error("Invalid username or password.")

    st.caption("Default admin: **admin** / **admin** (change after first login in Account).")

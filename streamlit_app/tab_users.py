"""Admin tab: create, list, delete users, reset passwords."""

from __future__ import annotations

import streamlit as st

from auth import admin_reset_password, create_user, delete_user, list_users
from session_auth import current_user_id
from styles import card_container


def render_users_tab() -> None:
    st.markdown("### User management")
    st.caption(
        "Create accounts for other people. Each user only sees their own goals and progress."
    )

    acting_admin_id = current_user_id()
    users = list_users()
    deletable = [u for u in users if u["id"] != acting_admin_id]

    with card_container():
        st.markdown("#### Existing users")
        if not users:
            st.info("No users yet.")
        else:
            for u in users:
                role = "Admin" if u["is_admin"] else "User"
                you = " · you" if u["id"] == acting_admin_id else ""
                st.markdown(f"- **{u['username']}** · {role}{you}")

    st.markdown("#### Create user")
    with st.form("create_user_form", clear_on_submit=True):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button("Create user", type="primary", use_container_width=True)

    if submitted:
        if new_password != confirm_password:
            st.error("Passwords do not match.")
            return
        ok, message = create_user(new_username, new_password, is_admin=False)
        if ok:
            st.success(message)
            st.rerun()
        else:
            st.error(message)

    if users:
        st.divider()
        st.markdown("#### Reset user password")
        st.caption("Admin can set a new password without the old one.")
        reset_candidates = [u for u in users if u["id"] != acting_admin_id]
        if reset_candidates:
            reset_by_id = {u["id"]: u for u in reset_candidates}
            reset_id = st.selectbox(
                "User",
                options=[u["id"] for u in reset_candidates],
                format_func=lambda uid: reset_by_id[uid]["username"],
                key="admin_reset_user_select",
            )
            new_pw = st.text_input("New password", type="password", key="admin_reset_pw")
            confirm_pw = st.text_input("Confirm password", type="password", key="admin_reset_pw2")
            if st.button("Reset password", key="admin_reset_btn", use_container_width=True):
                if new_pw != confirm_pw:
                    st.error("Passwords do not match.")
                else:
                    ok, message = admin_reset_password(reset_id, new_pw)
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)

    if deletable:
        st.divider()
        st.markdown("#### Delete user")
        st.caption("Deleting a user permanently removes their goals and progress.")

        user_by_id = {u["id"]: u for u in deletable}
        options = [u["id"] for u in deletable]
        selected_id = st.selectbox(
            "Select user to delete",
            options=options,
            format_func=lambda uid: user_by_id[uid]["username"],
            key="admin_delete_user_select",
        )
        selected = user_by_id[selected_id]
        st.warning(
            f"This will permanently delete **{selected['username']}** "
            f"and all of their IKR data."
        )
        confirm = st.checkbox(
            f"I understand — delete **{selected['username']}**",
            key="admin_delete_user_confirm",
        )
        if st.button(
            "Delete user",
            type="primary",
            disabled=not confirm,
            key="admin_delete_user_btn",
            use_container_width=True,
        ):
            ok, message = delete_user(selected_id, acting_admin_id=acting_admin_id)
            if ok:
                st.success(message)
                st.session_state.pop("admin_delete_user_confirm", None)
                st.rerun()
            else:
                st.error(message)

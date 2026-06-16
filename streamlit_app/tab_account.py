"""Account tab: password and Telegram settings."""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from auth import change_password, disconnect_user_telegram, get_user_telegram_settings
from notifications import send_summary_to_user
from notifiers.telegram_core import fetch_bot_info
from session_auth import current_user_id, current_username
from styles import card_container
from telegram_connect import create_connect_link, poll_auto_connect


def _telegram_poll_fragment(user_id: str) -> None:
    """Auto-poll Telegram; rerun app when linked."""
    status, message = poll_auto_connect(user_id)
    if status == "connected":
        st.rerun()
    elif status == "error":
        st.error(message)
    else:
        st.info("Tap **Start** in Telegram — linking automatically…")


def render_account_tab() -> None:
    st.markdown("### Account")
    st.caption("Manage your sign-in credentials and Telegram notifications.")

    user_id = current_user_id()

    with card_container():
        st.markdown(f"Signed in as **{current_username()}**")

        with st.form("change_password_form", clear_on_submit=True):
            st.markdown("#### Change password")
            current_password = st.text_input("Current password", type="password")
            new_password = st.text_input("New password", type="password")
            confirm_password = st.text_input("Confirm new password", type="password")
            submitted = st.form_submit_button("Change password", type="primary", use_container_width=True)

        if submitted:
            if new_password != confirm_password:
                st.error("New passwords do not match.")
                return
            ok, message = change_password(user_id, current_password, new_password)
            if ok:
                st.success(message)
            else:
                st.error(message)

    tg = get_user_telegram_settings(user_id)
    connected = bool(tg.get("telegram_chat_id") and tg.get("telegram_enabled"))

    with card_container():
        st.markdown("#### Telegram notifications")

        if connected:
            st.success(
                f"Connected to Telegram (chat id `{tg.get('telegram_chat_id')}`)."
            )
            st.caption(
                "Replies are checked every ~30s while this app is open. "
                "Use **Check Telegram replies** if a message wasn't answered."
            )
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("Send test summary", key="telegram_send_now_btn", use_container_width=True):
                    ok, message = send_summary_to_user(user_id)
                    if ok:
                        st.success(message)
                    else:
                        st.error(message)
            with c2:
                if st.button(
                    "Check Telegram replies",
                    key="telegram_poll_now_btn",
                    use_container_width=True,
                ):
                    from telegram_inbound import process_all_inbound_updates

                    with st.spinner("Checking Telegram…"):
                        results, err = process_all_inbound_updates()
                    if err:
                        st.error(err)
                    elif results:
                        for row in results:
                            detail = row.get("detail", "")
                            if row.get("ok"):
                                st.success(detail or "Reply sent.")
                            else:
                                st.error(detail or "Send failed.")
                    else:
                        st.info("No new Telegram messages.")
            with c3:
                if st.button("Disconnect Telegram", key="telegram_disconnect_btn", use_container_width=True):
                    disconnect_user_telegram(user_id)
                    st.success("Telegram disconnected.")
                    st.rerun()
        else:
            bot = fetch_bot_info()
            bot_username = (bot or {}).get("username")

            st.markdown(
                "Click the button below, tap **Start** in Telegram, and this page will "
                "connect automatically — no chat id needed."
            )

            connect_url, link_err = create_connect_link(user_id)
            if link_err:
                st.error(link_err)
            elif connect_url:
                st.link_button(
                    "Connect on Telegram",
                    connect_url,
                    type="primary",
                    use_container_width=True,
                )
                if bot_username:
                    st.caption(f"Bot: @{bot_username}")

                # Try immediately, then poll every 5s until linked or error
                status, message = poll_auto_connect(user_id)
                if status == "connected":
                    st.rerun()
                elif status == "error":
                    st.error(message)
                else:
                    try:
                        poll_fn = st.fragment(run_every=timedelta(seconds=5))(
                            _telegram_poll_fragment
                        )
                        poll_fn(user_id)
                    except TypeError:
                        # Older Streamlit without fragment run_every
                        st.info(
                            "After tapping **Start** in Telegram, refresh this page to finish linking."
                        )

        if tg.get("last_progress_update_at"):
            st.caption(f"Last progress save: {tg['last_progress_update_at']}")

        with st.expander("How it works"):
            st.markdown(
                "1. Click **Connect on Telegram**.\n"
                "2. Tap **Start** in the Telegram chat.\n"
                "3. Return here — linking completes automatically.\n\n"
                "**Update progress in Telegram (app not required):** "
                "send `1 5`, `1 +3`, `1 -2`, `Read: 3`, or `/goals`. "
                "Keep `python scripts/poll_loop.py` running for instant replies while the app is closed."
            )

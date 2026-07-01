"""Telegram command reference (table layout for bot messages)."""

from __future__ import annotations

import html


def format_commands_table(*, as_html: bool = False) -> str:
    """Monospace command reference (readable as a table in Telegram)."""
    body = (
        "COMMANDS        WHAT IT DOES\n"
        "──────────────  ─────────────────────────\n"
        "/goals          Goals + progress chart\n"
        "/status         Same as /goals\n"
        "/help           This command table\n"
        "\n"
        "YOU SEND        EXAMPLE\n"
        "──────────────  ─────────────────────────\n"
        "Set value       1 5\n"
        "Add             1 +3\n"
        "Subtract        2 -2\n"
        "Daily (today)   1 yes   ·   1 no\n"
        "Daily (date)    1 2026-07-01 yes\n"
        "By goal name    Read: 3\n"
    )
    title = "📖 IKR bot — quick reference"
    if as_html:
        return f"<b>{html.escape(title)}</b>\n\n<pre>{html.escape(body)}</pre>"
    return f"{title}\n\n{body}"


def telegram_help_text() -> str:
    return format_commands_table(as_html=True)


def telegram_help_plain() -> str:
    return format_commands_table(as_html=False)

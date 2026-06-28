"""Text formatting helpers shared by the connectors.

Agents emit a common Markdown subset (``**bold**``, ``*italic*`` / ``_italic_``,
`` `code` `` and fenced ``` blocks). Each platform renders a different flavour, so every
connector converts that subset to its own format and splits long replies to the
platform's size limit. These functions are pure and unit-tested.
"""
from __future__ import annotations

import html as _html
import re


def chunk(text: str, limit: int) -> list[str]:
    """Split *text* into ``<= limit`` pieces, preferring paragraph, then line, then word
    boundaries, and hard-splitting only as a last resort."""
    text = text or ""
    if len(text) <= limit:
        return [text] if text else []
    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        window = remaining[:limit]
        for sep in ("\n\n", "\n", " "):
            cut = window.rfind(sep)
            if cut > limit * 0.5:        # only if it doesn't waste too much of the window
                break
        else:
            cut = limit                  # no good boundary: hard cut
        cut = cut if cut > 0 else limit
        chunks.append(remaining[:cut].rstrip("\n"))
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return [c for c in chunks if c]


def strip_markdown(text: str) -> str:
    """Last-resort plain text: drop the markers that would otherwise show literally."""
    return text.replace("**", "").replace("`", "")


def markdown_to_telegram_html(text: str) -> str:
    """Convert the common Markdown subset to the HTML subset Telegram supports."""
    stash: list[str] = []

    def keep(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    text = re.sub(r"```(?:\w+)?\n?(.*?)```",
                  lambda m: keep(f"<pre>{_html.escape(m.group(1))}</pre>"), text, flags=re.S)
    text = re.sub(r"`([^`\n]+)`",
                  lambda m: keep(f"<code>{_html.escape(m.group(1))}</code>"), text)
    text = re.sub(
        r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)",
        lambda m: keep(f'<a href="{_html.escape(m.group(2), quote=True)}">{_html.escape(m.group(1))}</a>'),
        text)
    text = _html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)
    text = re.sub(r"(?<!\w)\*([^*\n]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_\n]+?)_(?!\w)", r"<i>\1</i>", text)
    for i, s in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", s)
    return text


def markdown_to_slack_mrkdwn(text: str) -> str:
    """Convert the common Markdown subset to Slack's ``mrkdwn``.

    Slack uses single ``*`` for bold and ``_`` for italic, and ``[text](url)`` becomes
    ``<url|text>``. Fenced/inline code already matches Slack, so they pass through."""
    stash: list[str] = []

    def keep(s: str) -> str:
        stash.append(s)
        return f"\x00{len(stash) - 1}\x00"

    # Protect code spans/blocks from the bold/italic rewrites (Slack syntax matches already).
    text = re.sub(r"```.*?```", lambda m: keep(m.group(0)), text, flags=re.S)
    text = re.sub(r"`[^`\n]+`", lambda m: keep(m.group(0)), text)
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)", r"<\2|\1>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text, flags=re.S)   # bold ** -> *
    for i, s in enumerate(stash):
        text = text.replace(f"\x00{i}\x00", s)
    return text

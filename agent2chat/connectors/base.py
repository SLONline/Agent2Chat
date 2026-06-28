"""Chat-platform connector abstraction.

A connector is everything platform-specific: it authenticates, receives inbound
messages, and sends replies. The :class:`~agent2chat.bridge.Bridge` drives it through
one small interface, so adding a platform never touches the bridge.

Two delivery styles both fit the same interface:

* **pull** (Telegram long polling, Slack Socket Mode): :meth:`Connector.listen` blocks
  in its own loop and calls ``on_message`` for each inbound message.
* **push** (Teams Bot Framework webhook): :meth:`Connector.listen` runs an HTTP server
  that calls ``on_message`` from its request handler threads.

Either way the bridge just supplies an ``on_message`` callback and a stop event.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class IncomingMessage:
    """One inbound message, normalised across platforms."""
    conversation_id: str            # opaque per-conversation id (used to route replies + workers)
    user_id: str                    # opaque sender id (matched against the allow-list)
    text: str = ""                  # message text (already de-mentioned where relevant)
    user_name: str = ""             # display/handle, for logs and /id
    command: str = ""               # bare slash-command name if the text is a command, else ""
    raw: dict = field(default_factory=dict)   # the untouched platform payload (escape hatch)


#: Callback the bridge hands to a connector. Receives each inbound message.
OnMessage = Callable[[IncomingMessage], None]


class ConnectorError(Exception):
    """Platform error with a user-facing message."""


class Connector:
    #: Stable platform identifier (matches the ``platform`` config field).
    name: str = ""

    def __init__(self, cfg) -> None:
        self.cfg = cfg

    # ---- lifecycle ---------------------------------------------------------
    def verify(self) -> str:
        """Authenticate against the platform and return a human label for the bot
        (e.g. ``@mybot``). Raises :class:`ConnectorError` if credentials are bad.
        Called once at startup before :meth:`listen`."""
        raise NotImplementedError

    def listen(self, on_message: OnMessage, stop: threading.Event) -> None:
        """Block, delivering inbound messages via *on_message* until *stop* is set."""
        raise NotImplementedError

    # ---- output ------------------------------------------------------------
    def send_message(self, conversation_id: str, text: str) -> None:
        """Send *text* to a conversation, formatting + splitting as the platform needs."""
        raise NotImplementedError

    def send_typing(self, conversation_id: str) -> None:
        """Optional 'typing…' hint. Default: no-op (cosmetic; never required)."""
        return None

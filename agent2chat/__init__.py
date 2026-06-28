"""Agent2Chat — connect a local AI agent (Claude Code, Codex or any CLI) to a chat
platform (Telegram, Slack or Microsoft Teams).

The package is split into two independent halves that the :mod:`~agent2chat.bridge`
glues together:

* **connectors** (:mod:`agent2chat.connectors`) speak to a chat platform. They receive
  messages and send replies. Telegram uses long polling, Slack uses Socket Mode and
  Teams uses a Bot Framework webhook — but the bridge sees one uniform interface.
* **adapters** (:mod:`agent2chat.adapters`) drive an AI agent's command-line tool.

The runtime depends only on the Python standard library, so it installs cleanly
anywhere and works behind NAT / a firewall (no public IP required for Telegram or
Slack; Teams needs a reachable webhook because the Bot Framework only pushes).
"""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]

"""Connector registry. New platforms drop a module here and register their class."""
from __future__ import annotations

from .base import Connector, ConnectorError, IncomingMessage, OnMessage
from .slack import SlackConnector
from .teams import TeamsConnector
from .telegram import TelegramConnector

#: Order matters: this is the order shown in the setup wizard.
REGISTRY: dict[str, type[Connector]] = {
    c.name: c for c in (TelegramConnector, SlackConnector, TeamsConnector)
}


def build(cfg) -> Connector:
    """Instantiate the connector named in ``cfg.platform``."""
    cls = REGISTRY.get(cfg.platform)
    if cls is None:
        raise ConnectorError(
            f"Unknown platform '{cfg.platform}'. Choose one of: {', '.join(REGISTRY)}."
        )
    return cls(cfg)


__all__ = [
    "Connector", "ConnectorError", "IncomingMessage", "OnMessage",
    "REGISTRY", "build",
]

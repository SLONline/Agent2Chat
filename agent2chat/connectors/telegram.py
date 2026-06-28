"""Telegram connector — long polling, standard library only.

Why long polling? The host needs no public IP / webhook, so it works behind NAT, a
home router, or a strict firewall. Every call retries with exponential backoff on
transient network/5xx errors and honours Telegram's ``429 retry_after`` flood control.
"""
from __future__ import annotations

import json
import logging
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .. import formatting
from .base import Connector, ConnectorError, IncomingMessage, OnMessage

log = logging.getLogger("agent2chat.telegram")

API_ROOT = "https://api.telegram.org"
MAX_MESSAGE_LEN = 4000          # Telegram's hard limit is 4096 UTF-16 units; keep a margin
SEND_TIMEOUT = 15

_ipv4_patched = False


def _prefer_ipv4() -> None:
    """Prefer IPv4 for outbound connections (idempotent, process-wide). Some hosts have a
    broken/slow IPv6 route to Telegram and urllib (unlike curl) has no Happy Eyeballs."""
    global _ipv4_patched
    if _ipv4_patched:
        return
    _orig = socket.getaddrinfo

    def _gai(host, port, family=0, *args, **kwargs):
        res = _orig(host, port, family, *args, **kwargs)
        v4 = [r for r in res if r[0] == socket.AF_INET]
        return v4 or res

    socket.getaddrinfo = _gai
    _ipv4_patched = True


class TelegramConnector(Connector):
    name = "telegram"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        token = cfg.telegram_token
        if not token or ":" not in token:
            raise ConnectorError("Invalid Telegram bot token.")
        _prefer_ipv4()
        self._token = token
        self._poll_timeout = cfg.poll_timeout
        self._opener = urllib.request.build_opener()

    # ---- Connector interface ----------------------------------------------
    def verify(self) -> str:
        me = self._call("getMe", timeout=15)
        return "@" + me.get("username", "bot")

    def listen(self, on_message: OnMessage, stop: threading.Event) -> None:
        self._register_commands()
        offset = 0
        while not stop.is_set():
            try:
                updates = self._get_updates(offset)
            except ConnectorError as e:
                log.error("getUpdates failed: %s", e)
                stop.wait(3)
                continue
            for upd in updates:
                offset = max(offset, upd["update_id"] + 1)
                msg = self._to_incoming(upd)
                if msg is not None:
                    on_message(msg)

    def send_message(self, conversation_id: str, text: str) -> None:
        for piece in formatting.chunk(text, MAX_MESSAGE_LEN) or ["(empty response)"]:
            base = {"chat_id": conversation_id, "disable_web_page_preview": "true"}
            try:
                self._call("sendMessage", {
                    **base, "text": formatting.markdown_to_telegram_html(piece), "parse_mode": "HTML",
                }, timeout=SEND_TIMEOUT)
            except ConnectorError as e:
                log.warning("HTML send failed, falling back to plain text: %s", e)
                self._call("sendMessage", {**base, "text": formatting.strip_markdown(piece)},
                           timeout=SEND_TIMEOUT)

    def send_typing(self, conversation_id: str) -> None:
        try:
            self._call("sendChatAction", {"chat_id": conversation_id, "action": "typing"},
                       timeout=8, retries=0)
        except ConnectorError:
            pass   # purely cosmetic

    # ---- translation -------------------------------------------------------
    def _to_incoming(self, update: dict) -> IncomingMessage | None:
        msg = update.get("message")
        if not msg:
            return None
        text = (msg.get("text") or msg.get("caption") or "").strip()
        user = msg.get("from", {})
        command = ""
        if text.startswith("/"):
            command = text.split()[0].lstrip("/").split("@")[0].lower()
        return IncomingMessage(
            conversation_id=str(msg["chat"]["id"]),
            user_id=str(user.get("id", "")),
            text=text,
            user_name=user.get("username") or user.get("first_name") or "",
            command=command,
            raw=update,
        )

    # ---- low-level client --------------------------------------------------
    def _register_commands(self) -> None:
        commands = [
            {"command": "id", "description": "show your Telegram ids (for the allow-list)"},
            {"command": "reset", "description": "start a fresh conversation"},
            {"command": "status", "description": "bridge status"},
            {"command": "help", "description": "show help"},
        ]
        try:
            self._call("setMyCommands", {"commands": json.dumps(commands)}, timeout=15)
        except ConnectorError as e:
            log.warning("setMyCommands failed (cosmetic): %s", e)

    def _get_updates(self, offset: int) -> list[dict]:
        return self._call("getUpdates", {
            "offset": offset, "timeout": self._poll_timeout,
            "allowed_updates": json.dumps(["message"]),
        }, timeout=self._poll_timeout + 15)

    def _call(self, method: str, params: dict | None = None, *, timeout: float = 65,
              retries: int = 5) -> dict:
        url = f"{API_ROOT}/bot{self._token}/{method}"
        data = urllib.parse.urlencode(params or {}, doseq=True).encode()
        attempt = 0
        while True:
            attempt += 1
            try:
                req = urllib.request.Request(url, data=data, method="POST")
                with self._opener.open(req, timeout=timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                if not body.get("ok"):
                    raise ConnectorError(f"{method}: {body.get('description', 'unknown error')}")
                return body["result"]
            except urllib.error.HTTPError as e:
                wait = self._retry_after(e)
                if wait is not None:
                    log.warning("Flood control on %s, waiting %ss", method, wait)
                    time.sleep(wait + 0.5)
                    continue
                if e.code >= 500 and attempt <= retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise ConnectorError(f"{method}: HTTP {e.code} {e.reason}") from e
            except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
                if attempt <= retries:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise ConnectorError(f"{method}: {e}") from e

    @staticmethod
    def _retry_after(err: urllib.error.HTTPError) -> int | None:
        if err.code != 429:
            return None
        try:
            payload = json.loads(err.read().decode("utf-8"))
            return int(payload.get("parameters", {}).get("retry_after", 1))
        except Exception:
            return int(err.headers.get("Retry-After", 1) or 1)

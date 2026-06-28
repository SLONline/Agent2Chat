"""Slack connector — Socket Mode, standard library only.

Socket Mode opens an outbound WebSocket to Slack, so — like Telegram long polling — it
needs no public URL and works behind NAT/firewalls. Setup:

1. Create a Slack app, enable **Socket Mode**, and add an app-level token with
   ``connections:write`` (``xapp-…`` → ``slack_app_token``).
2. Give the bot user OAuth scopes ``chat:write``, ``app_mentions:read`` and
   ``im:history`` / ``message.im`` events, then install it (``xoxb-…`` → ``slack_bot_token``).
3. Subscribe to the ``message.im`` and ``app_mention`` events.

The bot replies in the same channel/DM. Threaded replies keep each conversation tidy.
"""
from __future__ import annotations

import json
import logging
import re
import threading

from .. import formatting
from ..http_util import HttpError, request
from .base import Connector, ConnectorError, IncomingMessage, OnMessage
from .ws import WebSocket, WebSocketError

log = logging.getLogger("agent2chat.slack")

API = "https://slack.com/api"
MAX_MESSAGE_LEN = 3500          # Slack's limit is ~4000 chars per message; keep a margin


class SlackConnector(Connector):
    name = "slack"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._bot_token = cfg.slack_bot_token
        self._app_token = cfg.slack_app_token
        self._bot_user_id = ""      # filled in by verify(); used to strip @-mentions

    # ---- Connector interface ----------------------------------------------
    def verify(self) -> str:
        res = self._call("auth.test", token=self._bot_token)
        self._bot_user_id = res.get("user_id", "")
        return "@" + res.get("user", "bot")

    def listen(self, on_message: OnMessage, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                url = self._open_connection()
                ws = WebSocket.connect(url)
            except (ConnectorError, WebSocketError, OSError) as e:
                log.error("Socket Mode connect failed: %s; retry in 5s", e)
                stop.wait(5)
                continue
            log.info("Socket Mode connected")
            try:
                self._pump(ws, on_message, stop)
            except (WebSocketError, OSError) as e:
                log.warning("Socket Mode dropped: %s; reconnecting", e)
            finally:
                ws.close()

    def send_message(self, conversation_id: str, text: str) -> None:
        # conversation_id is "<channel>" or "<channel>:<thread_ts>" to keep a thread.
        channel, _, thread_ts = conversation_id.partition(":")
        for piece in formatting.chunk(text, MAX_MESSAGE_LEN) or ["(empty response)"]:
            params = {
                "channel": channel,
                "text": formatting.markdown_to_slack_mrkdwn(piece),
                "unfurl_links": False,
            }
            if thread_ts:
                params["thread_ts"] = thread_ts
            try:
                self._call("chat.postMessage", token=self._bot_token, json_body=params)
            except ConnectorError as e:
                log.warning("postMessage failed: %s", e)

    # ---- socket pump -------------------------------------------------------
    def _pump(self, ws: WebSocket, on_message: OnMessage, stop: threading.Event) -> None:
        while not stop.is_set():
            frame = ws.recv(timeout=1.0)
            if frame is None:
                continue                 # timeout (lets us re-check `stop`) or clean close
            try:
                envelope = json.loads(frame)
            except json.JSONDecodeError:
                continue
            kind = envelope.get("type")
            if kind == "hello":
                continue
            if kind == "disconnect":
                log.info("Slack asked us to reconnect (%s)", envelope.get("reason"))
                return
            if "envelope_id" in envelope:
                ws.send_text(json.dumps({"envelope_id": envelope["envelope_id"]}))   # ack
            if kind == "events_api":
                msg = self._to_incoming(envelope.get("payload", {}))
                if msg is not None:
                    on_message(msg)

    def _to_incoming(self, payload: dict) -> IncomingMessage | None:
        event = payload.get("event", {})
        etype = event.get("type")
        if etype not in ("message", "app_mention"):
            return None
        # Ignore the bot's own messages, edits, joins and other non-user noise.
        if event.get("bot_id") or event.get("subtype"):
            return None
        user = event.get("user", "")
        if not user or user == self._bot_user_id:
            return None
        text = self._strip_mention(event.get("text", "")).strip()
        channel = event.get("channel", "")
        thread_ts = event.get("thread_ts") or event.get("ts", "")
        command = ""
        if text.startswith("/"):
            command = text.split()[0].lstrip("/").lower()
        return IncomingMessage(
            conversation_id=f"{channel}:{thread_ts}",
            user_id=user,
            text=text,
            user_name=user,
            command=command,
            raw=payload,
        )

    def _strip_mention(self, text: str) -> str:
        if self._bot_user_id:
            text = re.sub(rf"<@{re.escape(self._bot_user_id)}>", "", text)
        return text

    # ---- low level ---------------------------------------------------------
    def _open_connection(self) -> str:
        res = self._call("apps.connections.open", token=self._app_token)
        url = res.get("url")
        if not url:
            raise ConnectorError("apps.connections.open returned no url")
        return url

    def _call(self, method: str, *, token: str, json_body: dict | None = None) -> dict:
        headers = {"Authorization": f"Bearer {token}"}
        try:
            if json_body is not None:
                res = request("POST", f"{API}/{method}", headers=headers, json_body=json_body)
            else:
                res = request("POST", f"{API}/{method}", headers=headers, form_body={})
        except HttpError as e:
            raise ConnectorError(f"{method}: {e}") from e
        if not res.get("ok"):
            raise ConnectorError(f"{method}: {res.get('error', 'unknown error')}")
        return res

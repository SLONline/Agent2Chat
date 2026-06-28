"""Microsoft Teams connector — Bot Framework, standard library only.

Unlike Telegram and Slack, the Bot Framework only *pushes*: Teams POSTs each message as
an "Activity" to your bot's messaging endpoint, so this connector runs a small HTTP
server (``/api/messages``) that must be reachable from Azure Bot Service. In practice you
expose it over HTTPS (a reverse proxy, an ``ngrok``/Dev Tunnel during development, or an
Azure App Service) and set that URL as the bot's messaging endpoint.

Replies are sent back to the per-message ``serviceUrl`` using an OAuth token obtained
from Azure AD with the bot's app id + secret (client-credentials flow). The token is
cached until shortly before it expires.

Setup:
1. Create an Azure Bot resource (multi-tenant or single-tenant) and an associated
   App Registration; note the **App ID** and a **client secret**.
2. Add the **Microsoft Teams** channel to the bot.
3. Set the messaging endpoint to ``https://<your-host>/api/messages``.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import formatting
from ..http_util import HttpError, request
from .base import Connector, ConnectorError, IncomingMessage, OnMessage

log = logging.getLogger("agent2chat.teams")

MAX_MESSAGE_LEN = 16000          # Teams accepts large messages; chunk generously anyway
_LOGIN_ROOT = "https://login.microsoftonline.com"
_BOT_SCOPE = "https://api.botframework.com/.default"


class TeamsConnector(Connector):
    name = "teams"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._app_id = cfg.teams_app_id
        self._app_password = cfg.teams_app_password
        self._tenant = cfg.teams_tenant_id or "botframework.com"   # botframework.com => multi-tenant
        self._host = cfg.webhook_host
        self._port = cfg.webhook_port
        self._token = ""
        self._token_exp = 0.0
        self._token_lock = threading.Lock()
        # conversation_id -> serviceUrl, so send_message knows where to post the reply.
        self._service_urls: dict[str, str] = {}

    # ---- Connector interface ----------------------------------------------
    def verify(self) -> str:
        self._get_token(force=True)          # fails loudly if the app id/secret are wrong
        return f"Teams app {self._app_id}"

    def listen(self, on_message: OnMessage, stop: threading.Event) -> None:
        connector = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):    # route through our logger, not stderr
                log.debug("%s - %s", self.address_string(), args[0] % args[1:])

            def do_GET(self):                # a trivial health check endpoint
                if self.path.rstrip("/") in ("/healthz", "/health"):
                    self._respond(200, {"status": "ok"})
                else:
                    self._respond(404, {"error": "not found"})

            def do_POST(self):
                if self.path.rstrip("/") != "/api/messages":
                    self._respond(404, {"error": "not found"})
                    return
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = self.rfile.read(length) if length else b""
                try:
                    activity = json.loads(body)
                except json.JSONDecodeError:
                    self._respond(400, {"error": "invalid json"})
                    return
                self._respond(200, {})       # ack immediately; processing happens async
                try:
                    msg = connector._to_incoming(activity)
                    if msg is not None:
                        on_message(msg)
                except Exception as e:       # a handler must never take down the server
                    log.exception("activity handling failed: %s", e)

            def _respond(self, status: int, payload: dict) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer((self._host, self._port), Handler)
        server.daemon_threads = True
        log.info("Teams messaging endpoint listening on http://%s:%d/api/messages",
                 self._host, self._port)
        t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
        t.start()
        try:
            while not stop.is_set():
                stop.wait(0.5)
        finally:
            server.shutdown()
            server.server_close()

    def send_message(self, conversation_id: str, text: str) -> None:
        service_url = self._service_urls.get(conversation_id)
        if not service_url:
            log.error("no serviceUrl known for conversation %s; cannot reply", conversation_id)
            return
        base = service_url.rstrip("/")
        url = f"{base}/v3/conversations/{conversation_id}/activities"
        for piece in formatting.chunk(text, MAX_MESSAGE_LEN) or ["(empty response)"]:
            activity = {
                "type": "message",
                "from": {"id": self._app_id},
                "conversation": {"id": conversation_id},
                "text": piece,
                "textFormat": "markdown",
            }
            try:
                request("POST", url, headers=self._auth_header(), json_body=activity)
            except HttpError as e:
                log.warning("reply post failed: %s", e)

    def send_typing(self, conversation_id: str) -> None:
        service_url = self._service_urls.get(conversation_id)
        if not service_url:
            return
        url = f"{service_url.rstrip('/')}/v3/conversations/{conversation_id}/activities"
        try:
            request("POST", url, headers=self._auth_header(),
                    json_body={"type": "typing", "conversation": {"id": conversation_id}})
        except HttpError:
            pass

    # ---- translation -------------------------------------------------------
    def _to_incoming(self, activity: dict) -> IncomingMessage | None:
        if activity.get("type") != "message":
            return None
        conversation = activity.get("conversation", {})
        conversation_id = conversation.get("id", "")
        if not conversation_id:
            return None
        service_url = activity.get("serviceUrl", "")
        if service_url:
            self._service_urls[conversation_id] = service_url
        sender = activity.get("from", {})
        text = (activity.get("text") or "").strip()
        # Teams prefixes @-mentions; the recipient is in entities, strip a leading bot name token.
        text = self._strip_mention(text, activity)
        command = ""
        if text.startswith("/"):
            command = text.split()[0].lstrip("/").lower()
        return IncomingMessage(
            conversation_id=conversation_id,
            user_id=sender.get("aadObjectId") or sender.get("id", ""),
            text=text,
            user_name=sender.get("name", ""),
            command=command,
            raw=activity,
        )

    @staticmethod
    def _strip_mention(text: str, activity: dict) -> str:
        for entity in activity.get("entities", []):
            if entity.get("type") == "mention":
                mention_text = entity.get("text", "")
                if mention_text:
                    text = text.replace(mention_text, "")
        return text.strip()

    # ---- auth --------------------------------------------------------------
    def _auth_header(self) -> dict:
        return {"Authorization": f"Bearer {self._get_token()}"}

    def _get_token(self, *, force: bool = False) -> str:
        with self._token_lock:
            if not force and self._token and time.time() < self._token_exp:
                return self._token
            url = f"{_LOGIN_ROOT}/{self._tenant}/oauth2/v2.0/token"
            try:
                res = request("POST", url, form_body={
                    "grant_type": "client_credentials",
                    "client_id": self._app_id,
                    "client_secret": self._app_password,
                    "scope": _BOT_SCOPE,
                })
            except HttpError as e:
                raise ConnectorError(f"Azure AD token request failed: {e}") from e
            token = res.get("access_token")
            if not token:
                raise ConnectorError("Azure AD returned no access_token (check app id/secret).")
            self._token = token
            self._token_exp = time.time() + int(res.get("expires_in", 3600)) - 60
            return token

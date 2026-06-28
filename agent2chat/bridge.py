"""The bridge: receive a message, run the agent, send the reply back — on any platform.

Concurrency model
-----------------
The connector delivers inbound messages via a callback (from a poll loop or webhook
threads). Each conversation gets its own worker thread and queue, so:
  * messages from the *same* conversation are processed strictly in order (the agent is
    never hit twice concurrently for one conversation), and
  * different conversations run in parallel.

The callback never blocks on a slow agent, so polling / webhook acks keep flowing and
the bot stays responsive (e.g. to ``/status``) even while a long task runs elsewhere.

Continuity is tracked on disk (a marker file per conversation dir), so it survives a
restart and ``/reset`` correctly starts over.
"""
from __future__ import annotations

import logging
import queue
import re
import signal
import threading
from pathlib import Path

from . import __version__, adapters, connectors
from .config import Config

log = logging.getLogger("agent2chat.bridge")

_HELP = (
    "🤖 *Agent2Chat*\n"
    "Send me a message and I'll pass it to the connected AI agent.\n\n"
    "Commands:\n"
    "/id — show your ids (for the allow-list)\n"
    "/reset — start a fresh conversation\n"
    "/status — bridge status\n"
    "/help — this help"
)


class Bridge:
    def __init__(self, cfg: Config, *, connector: connectors.Connector | None = None) -> None:
        self.cfg = cfg
        self.connector = connector or connectors.build(cfg)
        self.adapter = adapters.build(cfg)
        self._allowed = set(cfg.allowed_user_ids)
        self._stop = threading.Event()
        self._workers: dict[str, "_ConversationWorker"] = {}
        self._workers_lock = threading.Lock()

    # ---- lifecycle ---------------------------------------------------------
    def run(self) -> None:
        label = self._connect()
        log.info("Connected as %s — platform=%s, agent=%s, authorized users=%s",
                 label, self.cfg.platform, self.cfg.agent, sorted(self._allowed) or "(none!)")
        if not self._allowed:
            log.warning("No allowed_user_ids configured — the bot will refuse everyone. "
                        "Message the bot and use /id, then add your id to the config.")
        self._install_signal_handlers()
        try:
            self.connector.listen(self._on_message, self._stop)
        finally:
            self._shutdown()

    def _connect(self) -> str:
        """Verify credentials at startup, retrying so a not-yet-ready network at boot
        doesn't crash the service (it just waits for connectivity)."""
        delay = 2
        while not self._stop.is_set():
            try:
                return self.connector.verify()
            except Exception as e:
                log.warning("%s not reachable yet (%s); retrying in %ss",
                            self.cfg.platform, e, delay)
                self._stop.wait(delay)
                delay = min(delay * 2, 60)
        return "(stopped)"

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self._stop.set())
            except ValueError:
                pass  # not in main thread (e.g. tests) — caller drives _stop

    def _shutdown(self) -> None:
        log.info("Shutting down…")
        self._stop.set()
        with self._workers_lock:
            for w in self._workers.values():
                w.stop()
        for w in list(self._workers.values()):
            w.join(timeout=5)

    # ---- dispatch ----------------------------------------------------------
    def _on_message(self, msg: connectors.IncomingMessage) -> None:
        try:
            if msg.command and self._handle_command(msg):
                return
            if msg.user_id not in self._allowed:
                log.warning("Refused message from unauthorized user %s (%s)",
                            msg.user_id, msg.user_name)
                self.connector.send_message(
                    msg.conversation_id,
                    "⛔ You're not authorized to use this bot.\n"
                    f"Your user id is `{msg.user_id}` — ask the owner to add it.",
                )
                return
            if not msg.text:
                self.connector.send_message(msg.conversation_id, "ℹ️ Send me some text to get started.")
                return
            self._enqueue(msg)
        except Exception as e:
            log.exception("dispatch error: %s", e)

    def _handle_command(self, msg: connectors.IncomingMessage) -> bool:
        cmd = msg.command
        if cmd in ("start", "help"):
            self.connector.send_message(msg.conversation_id, _HELP)
            return True
        if cmd == "id":
            self.connector.send_message(
                msg.conversation_id,
                f"user id: `{msg.user_id}`\nconversation id: `{msg.conversation_id}`")
            return True
        if cmd == "status":
            authed = "✅" if msg.user_id in self._allowed else "⛔ (not authorized)"
            self.connector.send_message(
                msg.conversation_id,
                f"🤖 Agent2Chat v{__version__}\nplatform: {self.cfg.platform}\n"
                f"agent: {self.cfg.agent}\nyou: {authed}")
            return True
        if cmd == "reset":
            if msg.user_id in self._allowed:
                self._reset_conversation(msg.conversation_id)
                self.connector.send_message(msg.conversation_id, "🔄 Fresh conversation started.")
            return True
        return False  # not a known command → treat as a normal prompt

    # ---- per-conversation workers -----------------------------------------
    def _enqueue(self, msg: connectors.IncomingMessage) -> None:
        with self._workers_lock:
            worker = self._workers.get(msg.conversation_id)
            if worker is None:
                worker = _ConversationWorker(msg.conversation_id, self)
                self._workers[msg.conversation_id] = worker
                worker.start()
        worker.submit(msg)

    _SAFE = re.compile(r"[^A-Za-z0-9._-]+")

    def conversation_dir(self, conversation_id: str) -> Path:
        # Conversation ids vary wildly across platforms (Teams ids contain ':' and '@'),
        # so sanitize into a stable, filesystem-safe directory name.
        safe = self._SAFE.sub("_", conversation_id).strip("_") or "conversation"
        return self.cfg.path_workdir() / safe

    def _reset_conversation(self, conversation_id: str) -> None:
        import shutil
        d = self.conversation_dir(conversation_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)

    @staticmethod
    def _marker(work_dir: Path) -> Path:
        return work_dir / ".a2c_started"

    def process(self, msg: connectors.IncomingMessage) -> None:
        """Run the agent for one message and reply. Runs inside a conversation worker."""
        work_dir = self.conversation_dir(msg.conversation_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        is_cont = self._marker(work_dir).exists()
        with self._keep_typing(msg.conversation_id):
            try:
                reply = self.adapter.run(msg.text, work_dir=work_dir, is_continuation=is_cont)
            except Exception as e:
                log.error("agent run failed for %s: %s", msg.conversation_id, e)
                self.connector.send_message(msg.conversation_id, f"⚠️ Agent error: {e}")
                return
        try:
            self._marker(work_dir).touch()
        except OSError:
            pass
        self.connector.send_message(msg.conversation_id, reply or "(the agent returned no output)")

    def _keep_typing(self, conversation_id: str):
        """Context manager that keeps a 'typing…' hint alive for the whole agent run."""
        bridge = self

        class _Typing:
            def __enter__(self):
                self._stop = threading.Event()
                self._t = threading.Thread(target=self._loop, daemon=True)
                self._t.start()
                return self

            def _loop(self):
                while not self._stop.is_set():
                    try:
                        bridge.connector.send_typing(conversation_id)
                    except Exception:
                        pass
                    self._stop.wait(4)

            def __exit__(self, *exc):
                self._stop.set()
                self._t.join(timeout=1)

        return _Typing()


class _ConversationWorker(threading.Thread):
    """Serializes processing for a single conversation."""

    def __init__(self, conversation_id: str, bridge: Bridge) -> None:
        super().__init__(daemon=True, name=f"conv-{conversation_id[:24]}")
        self.conversation_id = conversation_id
        self.bridge = bridge
        self.q: queue.Queue = queue.Queue()

    def submit(self, msg) -> None:
        self.q.put(msg)

    def stop(self) -> None:
        self.q.put(None)

    def run(self) -> None:
        while True:
            msg = self.q.get()
            if msg is None:
                return
            try:
                self.bridge.process(msg)
            except Exception as e:   # a worker must never die silently
                log.exception("worker %s crashed: %s", self.conversation_id, e)

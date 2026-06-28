import threading
import time

from agent2chat.bridge import Bridge
from agent2chat.config import Config
from agent2chat.connectors.base import Connector, IncomingMessage


class FakeConnector(Connector):
    name = "fake"

    def __init__(self, cfg):
        super().__init__(cfg)
        self.sent: list[tuple[str, str]] = []

    def verify(self):
        return "fake-bot"

    def send_message(self, conversation_id, text):
        self.sent.append((conversation_id, text))

    def send_typing(self, conversation_id):
        pass


def _bridge(monkeypatch, allowed=("u1",), reply="AGENT REPLY"):
    cfg = Config(platform="telegram", agent="claude-code", telegram_token="1:x",
                 allowed_user_ids=list(allowed))
    fake = FakeConnector(cfg)
    bridge = Bridge(cfg, connector=fake)

    runs = []

    def fake_run(prompt, *, work_dir, is_continuation):
        runs.append((prompt, is_continuation))
        return reply

    monkeypatch.setattr(bridge.adapter, "run", fake_run)
    return bridge, fake, runs


def _msg(text="hi", user="u1", conv="c1", command=""):
    return IncomingMessage(conversation_id=conv, user_id=user, text=text, command=command)


def _wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_unauthorized_user_refused(monkeypatch):
    bridge, fake, runs = _bridge(monkeypatch, allowed=("owner",))
    bridge._on_message(_msg(user="intruder"))
    assert runs == []
    assert any("not authorized" in t for _, t in fake.sent)


def test_help_command(monkeypatch):
    bridge, fake, _ = _bridge(monkeypatch)
    bridge._on_message(_msg(text="/help", command="help"))
    assert any("Agent2Chat" in t for _, t in fake.sent)


def test_id_command_reports_ids(monkeypatch):
    bridge, fake, _ = _bridge(monkeypatch)
    bridge._on_message(_msg(text="/id", command="id", user="u1", conv="c9"))
    body = fake.sent[-1][1]
    assert "u1" in body and "c9" in body


def test_authorized_message_runs_agent_and_replies(monkeypatch):
    bridge, fake, runs = _bridge(monkeypatch, reply="42")
    bridge._on_message(_msg(text="what is 6x7"))
    assert _wait_for(lambda: fake.sent)
    bridge._shutdown()
    assert runs and runs[0][0] == "what is 6x7"
    assert ("c1", "42") in fake.sent


def test_continuation_marker(monkeypatch, tmp_path):
    bridge, fake, runs = _bridge(monkeypatch)
    bridge.cfg.workdir = str(tmp_path)
    bridge._on_message(_msg(text="first"))
    assert _wait_for(lambda: len(fake.sent) >= 1)
    bridge._on_message(_msg(text="second"))
    assert _wait_for(lambda: len(runs) >= 2)
    bridge._shutdown()
    assert runs[0][1] is False     # first turn: not a continuation
    assert runs[1][1] is True      # second turn: continuation


def test_conversation_dir_sanitized(monkeypatch, tmp_path):
    bridge, _, _ = _bridge(monkeypatch)
    bridge.cfg.workdir = str(tmp_path)
    d = bridge.conversation_dir("19:abc@thread.tacv2")
    assert d.parent == tmp_path
    assert "/" not in d.name and ":" not in d.name and "@" not in d.name

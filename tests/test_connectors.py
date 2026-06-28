from agent2chat.config import Config
from agent2chat.connectors.slack import SlackConnector
from agent2chat.connectors.teams import TeamsConnector
from agent2chat.connectors.telegram import TelegramConnector


def test_telegram_to_incoming_text():
    c = TelegramConnector(Config(platform="telegram", agent="codex", telegram_token="1:x"))
    msg = c._to_incoming({
        "update_id": 5,
        "message": {"chat": {"id": -100}, "from": {"id": 77, "username": "ann"}, "text": "hello"},
    })
    assert msg.conversation_id == "-100"
    assert msg.user_id == "77"
    assert msg.user_name == "ann"
    assert msg.command == ""


def test_telegram_to_incoming_command():
    c = TelegramConnector(Config(platform="telegram", agent="codex", telegram_token="1:x"))
    msg = c._to_incoming({"update_id": 1, "message": {
        "chat": {"id": 1}, "from": {"id": 2}, "text": "/status@mybot extra"}})
    assert msg.command == "status"


def test_telegram_ignores_non_message():
    c = TelegramConnector(Config(platform="telegram", agent="codex", telegram_token="1:x"))
    assert c._to_incoming({"update_id": 1, "edited_message": {}}) is None


def _slack():
    return SlackConnector(Config(platform="slack", agent="codex",
                                 slack_bot_token="xoxb-1", slack_app_token="xapp-1"))


def test_slack_message_event():
    c = _slack()
    c._bot_user_id = "UBOT"
    msg = c._to_incoming({"event": {
        "type": "app_mention", "user": "UALICE", "channel": "C1",
        "ts": "123.45", "text": "<@UBOT> hello there"}})
    assert msg.conversation_id == "C1:123.45"
    assert msg.user_id == "UALICE"
    assert msg.text == "hello there"


def test_slack_ignores_bot_and_self():
    c = _slack()
    c._bot_user_id = "UBOT"
    assert c._to_incoming({"event": {"type": "message", "bot_id": "B1", "text": "x"}}) is None
    assert c._to_incoming({"event": {"type": "message", "user": "UBOT", "text": "x"}}) is None
    assert c._to_incoming({"event": {"type": "message", "subtype": "message_changed"}}) is None


def _teams():
    return TeamsConnector(Config(platform="teams", agent="codex",
                                 teams_app_id="appid", teams_app_password="secret"))


def test_teams_message_activity():
    c = _teams()
    msg = c._to_incoming({
        "type": "message",
        "text": "<at>Bot</at> do the thing",
        "serviceUrl": "https://smba.example/v3/",
        "conversation": {"id": "19:abc@thread.tacv2"},
        "from": {"id": "29:user", "name": "Bob", "aadObjectId": "aad-123"},
        "entities": [{"type": "mention", "text": "<at>Bot</at>"}],
    })
    assert msg.conversation_id == "19:abc@thread.tacv2"
    assert msg.user_id == "aad-123"
    assert msg.user_name == "Bob"
    assert msg.text == "do the thing"
    # serviceUrl is cached so a later reply knows where to post.
    assert c._service_urls["19:abc@thread.tacv2"] == "https://smba.example/v3/"


def test_teams_ignores_non_message():
    c = _teams()
    assert c._to_incoming({"type": "typing"}) is None

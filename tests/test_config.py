import json

import pytest

from agent2chat.config import Config, ConfigError, load, save


def test_telegram_config_valid():
    cfg = Config(platform="telegram", agent="claude-code", telegram_token="123:abc",
                 allowed_user_ids=["42"])
    cfg.validate()   # must not raise


def test_unknown_platform_rejected():
    with pytest.raises(ConfigError):
        Config(platform="discord", agent="claude-code").validate()


def test_telegram_requires_token():
    with pytest.raises(ConfigError):
        Config(platform="telegram", agent="claude-code", telegram_token="nope").validate()


def test_slack_requires_both_tokens():
    cfg = Config(platform="slack", agent="codex", slack_bot_token="xoxb-1")
    with pytest.raises(ConfigError):
        cfg.validate()
    cfg.slack_app_token = "xapp-1"
    cfg.validate()


def test_teams_requires_app_credentials():
    with pytest.raises(ConfigError):
        Config(platform="teams", agent="codex", teams_app_id="id").validate()
    Config(platform="teams", agent="codex", teams_app_id="id",
           teams_app_password="secret").validate()


def test_allowed_ids_must_be_strings():
    with pytest.raises(ConfigError):
        Config(platform="telegram", agent="codex", telegram_token="1:2",
               allowed_user_ids=[42]).validate()


def test_redacted_masks_secrets():
    cfg = Config(platform="slack", agent="codex",
                 slack_bot_token="xoxb-supersecret-token",
                 slack_app_token="xapp-anothersecret")
    red = cfg.redacted()
    assert "supersecret" not in json.dumps(red)
    assert red["slack_bot_token"].startswith("xoxb-")


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "config.json"
    cfg = Config(platform="telegram", agent="claude-code", telegram_token="9:secret",
                 allowed_user_ids=["7"])
    save(cfg, p)
    assert oct(p.stat().st_mode)[-3:] == "600"
    loaded = load(p)
    assert loaded.platform == "telegram"
    assert loaded.allowed_user_ids == ["7"]


def test_env_override(tmp_path, monkeypatch):
    p = tmp_path / "config.json"
    save(Config(platform="telegram", agent="codex", telegram_token="1:placeholder"), p)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:fromenv")
    assert load(p).telegram_token == "999:fromenv"

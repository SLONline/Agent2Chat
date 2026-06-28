"""Configuration loading, validation and persistence.

Config is a small JSON document stored at ``$AGENT2CHAT_CONFIG`` or, by default,
``~/.config/agent2chat/config.json``. The file holds platform secrets (bot tokens,
signing/app secrets), so it is always written with ``0600`` permissions, locked into
a ``0700`` directory, and never logged in full (see :meth:`Config.redacted`).

Secrets may instead be supplied via the environment, keeping them out of the file
entirely — see :func:`load`.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_ENV = "AGENT2CHAT_CONFIG"
DEFAULT_PATH = Path.home() / ".config" / "agent2chat" / "config.json"

#: Supported chat platforms (the ``platform`` config field).
PLATFORMS = ("telegram", "slack", "teams")
#: Supported agent adapters (the ``agent`` config field).
AGENTS = ("claude-code", "codex", "generic")


class ConfigError(Exception):
    """Raised when the configuration is missing or invalid (message is user-facing)."""


@dataclass
class Config:
    # ---- what to connect ---------------------------------------------------
    platform: str                       # telegram | slack | teams
    agent: str                          # claude-code | codex | generic

    # ---- who may drive the agent ------------------------------------------
    # Platform-native user ids (kept as strings so Telegram ints and Slack/Teams
    # opaque ids share one field). Empty list => the bot refuses everyone.
    allowed_user_ids: list[str] = field(default_factory=list)

    # ---- agent execution ---------------------------------------------------
    workdir: str = ""                   # base dir for per-conversation working directories
    command: list[str] | None = None    # optional override of the first-turn command
    continue_command: list[str] | None = None   # optional override of the follow-up command
    agent_timeout: int = 600            # seconds before a single agent run is killed

    # ---- Telegram ----------------------------------------------------------
    telegram_token: str = ""            # bot token from @BotFather  ("<id>:<secret>")
    poll_timeout: int = 50              # long-poll timeout for getUpdates

    # ---- Slack (Socket Mode) ----------------------------------------------
    slack_bot_token: str = ""           # xoxb-… (chat:write, etc.)
    slack_app_token: str = ""           # xapp-… (connections:write — enables Socket Mode)

    # ---- Microsoft Teams (Bot Framework) ----------------------------------
    teams_app_id: str = ""              # Azure AD app (client) id of the bot
    teams_app_password: str = ""        # client secret
    teams_tenant_id: str = ""           # "" => multi-tenant (botframework.com authority)
    webhook_host: str = "0.0.0.0"       # bind address for the Teams messaging endpoint
    webhook_port: int = 3978            # port for the Teams messaging endpoint (/api/messages)

    def path_workdir(self) -> Path:
        return Path(self.workdir).expanduser() if self.workdir else (_state_dir() / "chats")

    # ---- validation --------------------------------------------------------
    def validate(self) -> None:
        if self.platform not in PLATFORMS:
            raise ConfigError(f"'platform' must be one of: {', '.join(PLATFORMS)}.")
        if self.agent not in AGENTS:
            raise ConfigError(f"'agent' must be one of: {', '.join(AGENTS)}.")
        if not isinstance(self.allowed_user_ids, list) or not all(
            isinstance(i, str) for i in self.allowed_user_ids
        ):
            raise ConfigError("'allowed_user_ids' must be a list of strings.")
        if self.agent_timeout <= 0:
            raise ConfigError("'agent_timeout' must be positive.")
        getattr(self, f"_validate_{self.platform}")()

    def _validate_telegram(self) -> None:
        if not self.telegram_token or ":" not in self.telegram_token:
            raise ConfigError("Telegram needs 'telegram_token' (format '<id>:<secret>').")

    def _validate_slack(self) -> None:
        if not self.slack_bot_token.startswith("xoxb-"):
            raise ConfigError("Slack needs a bot token 'slack_bot_token' (starts with 'xoxb-').")
        if not self.slack_app_token.startswith("xapp-"):
            raise ConfigError(
                "Slack Socket Mode needs an app-level token 'slack_app_token' (starts with 'xapp-')."
            )

    def _validate_teams(self) -> None:
        if not self.teams_app_id or not self.teams_app_password:
            raise ConfigError("Teams needs 'teams_app_id' and 'teams_app_password'.")
        if not (0 < self.webhook_port < 65536):
            raise ConfigError("'webhook_port' must be a valid TCP port.")

    def redacted(self) -> dict:
        """A copy safe to print/log: every secret is masked."""
        d = asdict(self)
        for key in ("telegram_token", "slack_bot_token", "slack_app_token",
                    "teams_app_password"):
            d[key] = _mask(d.get(key) or "")
        return d


def _mask(secret: str) -> str:
    if not secret:
        return ""
    return (secret[:6] + "…" + secret[-2:]) if len(secret) > 10 else "set"


def _state_dir() -> Path:
    return Path(
        os.environ.get("AGENT2CHAT_STATE", Path.home() / ".local" / "state" / "agent2chat")
    ).expanduser()


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_ENV, DEFAULT_PATH)).expanduser()


#: Map of environment variable -> config field. Lets you keep secrets out of the file.
_ENV_OVERRIDES = {
    "TELEGRAM_BOT_TOKEN": "telegram_token",
    "SLACK_BOT_TOKEN": "slack_bot_token",
    "SLACK_APP_TOKEN": "slack_app_token",
    "TEAMS_APP_ID": "teams_app_id",
    "TEAMS_APP_PASSWORD": "teams_app_password",
    "TEAMS_TENANT_ID": "teams_tenant_id",
}


def load(path: Path | None = None) -> Config:
    p = path or config_path()
    if not p.exists():
        raise ConfigError(f"No config at {p}. Run 'python -m agent2chat setup' first.")
    try:
        raw = json.loads(p.read_text("utf-8"))
    except json.JSONDecodeError as e:
        raise ConfigError(f"Config at {p} is not valid JSON: {e}") from e
    for env, field_name in _ENV_OVERRIDES.items():
        if value := os.environ.get(env):
            raw[field_name] = value
    known = set(Config.__dataclass_fields__)
    cfg = Config(**{k: v for k, v in raw.items() if k in known})
    cfg.validate()
    return cfg


def save(cfg: Config, path: Path | None = None) -> Path:
    cfg.validate()
    p = path or config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(p.parent, stat.S_IRWXU)   # 0700 — it holds secret-bearing files
    except OSError:
        pass
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(asdict(cfg), indent=2, ensure_ascii=False), "utf-8")
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)   # 0600
    os.replace(tmp, p)
    return p

# Agent2Chat

[![CI](https://github.com/SLOnline/Agent2Chat/actions/workflows/ci.yml/badge.svg)](https://github.com/SLOnline/Agent2Chat/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Connect a local AI agent — **Claude Code**, **Codex**, or any CLI — to your team chat.
Message the bot, it runs the agent in a per-conversation working directory, and sends the
reply back. One bridge, three platforms:

| Platform | Transport | Public URL needed? |
| --- | --- | --- |
| **Telegram** | long polling | no |
| **Slack** | Socket Mode (WebSocket) | no |
| **Microsoft Teams** | Bot Framework webhook | yes (HTTPS endpoint) |

The runtime uses the **Python standard library only** — no `requests`, no
`python-telegram-bot`, no Slack/Teams SDKs (the Socket Mode WebSocket client is built in).
That means it installs cleanly anywhere and runs behind NAT/firewalls for Telegram and
Slack.

> Inspired by [Agent2Telegram](https://github.com/petrludwig-collab/Agent2Telegram);
> generalised to multiple chat platforms behind a small connector abstraction.

---

## How it works

```
chat platform ──▶ Connector ──▶ Bridge ──▶ Adapter ──▶ agent CLI
   (Telegram/        (receive/     (route,    (run the      (claude / codex / …)
    Slack/Teams)      send)         allow-list, subprocess)
                                    per-convo
                                    workers)
```

- **Connectors** (`agent2chat/connectors/`) speak one platform each and expose a uniform
  interface (`verify`, `listen`, `send_message`).
- **Adapters** (`agent2chat/adapters/`) wrap an agent's command-line tool. Continuity is
  free: each conversation gets its own working directory plus the agent's own
  "continue" flag.
- **Bridge** (`agent2chat/bridge.py`) is platform- and agent-agnostic. One worker thread
  per conversation keeps messages ordered within a chat and parallel across chats.

---

## Quick start

The runtime is stdlib-only, so you don't need to install anything to run it — just
clone and go:

```bash
git clone https://github.com/SLOnline/Agent2Chat.git
cd Agent2Chat
python3 -m agent2chat setup     # interactive: pick platform + agent, enter secrets
python3 -m agent2chat doctor    # verify config, agent binary and platform connectivity
python3 -m agent2chat run       # start the bridge
```

Want the bare `agent2chat` command on your PATH (and to run the tests)? Install it into
a virtual environment:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
agent2chat run
```

> **Ubuntu/Debian: `error: externally-managed-environment`?** That's
> [PEP 668](https://peps.python.org/pep-0668/) refusing to let `pip` touch the system
> Python. Either run from source with `python3 -m agent2chat …` (no install needed — see
> above), use the venv above (`sudo apt install python3-venv` if missing), or
> `pipx install .`. Don't use `--break-system-packages`.

In chat, message the bot. Built-in commands:

| Command | Action |
| --- | --- |
| `/help` | show help |
| `/id` | show your user + conversation id (for the allow-list) |
| `/status` | bridge status |
| `/reset` | start a fresh conversation |

Anyone not in `allowed_user_ids` is refused — send `/id`, then add your id to the config.

---

## Platform setup

### Telegram
1. Talk to [@BotFather](https://t.me/BotFather), create a bot, copy the token.
2. `platform: "telegram"`, set `telegram_token`.
3. Run the bridge, message your bot, `/id`, add your id to `allowed_user_ids`.

### Slack (Socket Mode)
1. Create a Slack app → enable **Socket Mode**.
2. Add an **app-level token** with `connections:write` → `slack_app_token` (`xapp-…`).
3. Add bot scopes `chat:write`, `app_mentions:read`, `im:history`; install the app →
   `slack_bot_token` (`xoxb-…`).
4. Subscribe to events `app_mention` and `message.im`.
5. `platform: "slack"`, set both tokens. DM the bot or @-mention it in a channel.

### Microsoft Teams (Bot Framework)
1. Create an **Azure Bot** resource + App Registration; note the **App ID** and a
   **client secret**.
2. Add the **Microsoft Teams** channel.
3. Set the messaging endpoint to `https://<your-host>/api/messages` (use a reverse proxy
   or a dev tunnel to reach `webhook_port`, default `3978`).
4. `platform: "teams"`, set `teams_app_id`, `teams_app_password`, and `teams_tenant_id`
   (blank for multi-tenant).

See [SECURITY.md](SECURITY.md) for the Teams webhook hardening notes.

---

## Configuration

Config lives at `~/.config/agent2chat/config.json` (override with `$AGENT2CHAT_CONFIG`).
See [`config.example.json`](config.example.json). Secrets may instead come from the
environment, keeping them out of the file:

```
TELEGRAM_BOT_TOKEN  SLACK_BOT_TOKEN  SLACK_APP_TOKEN
TEAMS_APP_ID  TEAMS_APP_PASSWORD  TEAMS_TENANT_ID
```

Key fields:

| Field | Meaning |
| --- | --- |
| `platform` | `telegram` \| `slack` \| `teams` |
| `agent` | `claude-code` \| `codex` \| `generic` |
| `allowed_user_ids` | who may drive the agent (list of strings) |
| `workdir` | base dir for per-conversation working directories |
| `command` / `continue_command` | override the agent's argv (use `{prompt}`) |
| `agent_timeout` | seconds before a run is killed |

### Generic agent

Point Agent2Chat at any CLI:

```json
{
  "platform": "slack",
  "agent": "generic",
  "command": ["my-agent", "--prompt", "{prompt}"],
  "continue_command": ["my-agent", "--resume", "--prompt", "{prompt}"]
}
```

---

## Run as a service

Run multiple bridges from one install by pointing each at its own config:

```bash
python -m agent2chat run --config /etc/agent2chat/telegram.json
python -m agent2chat run --config /etc/agent2chat/slack.json
```

A minimal systemd unit:

```ini
[Unit]
Description=Agent2Chat (slack)
After=network-online.target

[Service]
ExecStart=/usr/bin/python -m agent2chat run --config /etc/agent2chat/slack.json
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

### Proactive notifications

For cron jobs / background scripts to ping you (e.g. "build finished ✅"):

```bash
python -m agent2chat notify "build finished ✅"
echo "deploy done" | python -m agent2chat notify
```

---

## Development

```bash
pip install -e ".[dev]"
pytest -q
```

Adding a platform: drop a module in `agent2chat/connectors/`, subclass `Connector`,
register it in `connectors/__init__.py`. The bridge needs no changes.

## License

MIT — see [LICENSE](LICENSE).

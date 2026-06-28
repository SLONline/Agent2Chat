"""Guided, step-by-step Slack app setup.

Slack won't let a script create *and* fully install an app unattended (the configuration
token, the app-level token and the install click all require a human in the browser).
What it *does* support is "Create app from a manifest" — so this helper does the next
best thing: it asks for an app name, prints the exact manifest tailored to that name, and
walks you through each remaining click, pausing between steps and finally collecting the
two tokens straight into your config.

Run it standalone (``python -m agent2chat slack-init``) or let ``setup`` call it when you
pick Slack.
"""
from __future__ import annotations

from . import adapters
from .config import Config, config_path, save
from .wizard import _ask, _choose

APPS_URL = "https://api.slack.com/apps"


def build_manifest(app_name: str) -> str:
    """Return a Slack app manifest (YAML) for a Socket Mode bot with the given name.

    Stdlib-only: the name is the only variable, so we template the YAML directly and
    escape it for safe embedding in a double-quoted scalar.
    """
    safe = app_name.replace("\\", "\\\\").replace('"', '\\"')
    return f"""display_information:
  name: "{safe}"
  description: "Connects an AI agent to Slack via Agent2Chat"
features:
  bot_user:
    display_name: "{safe}"
    always_online: true
  app_home:
    home_tab_enabled: false
    messages_tab_enabled: true
    messages_tab_read_only_enabled: false
oauth_config:
  scopes:
    bot:
      - chat:write
      - app_mentions:read
      - im:history
      - im:read
settings:
  event_subscriptions:
    bot_events:
      - app_mention
      - message.im
  interactivity:
    is_enabled: false
  socket_mode_enabled: true
  org_deploy_enabled: false
  token_rotation_enabled: false
"""


def _pause(prompt: str = "Press Enter when done") -> None:
    try:
        input(f"   ↳ {prompt}… ")
    except EOFError:
        pass  # non-interactive (e.g. piped) — just continue


def _rule(char: str = "─", width: int = 64) -> str:
    return char * width


def collect_tokens() -> tuple[str, str, str]:
    """Walk the user through creating + installing the Slack app and return
    ``(bot_token, app_token, app_name)``."""
    print("\n" + _rule("="))
    print(" Slack setup — guided")
    print(_rule("="))
    print("Slack needs a few clicks in the browser. I'll show the manifest to paste and\n"
          "pause at each step. Nothing here leaves your machine.\n")

    app_name = _ask("First, name your Slack app", "Agent2Chat") or "Agent2Chat"
    manifest = build_manifest(app_name)

    print(f"\n[1/6]  Open {APPS_URL}")
    print("       Click  “Create New App”  →  “From a manifest”.")
    _pause("Press Enter once you're on the manifest screen")

    print("\n[2/6]  Pick the workspace to install into, then click “Next”.")
    _pause()

    print("\n[3/6]  Switch the manifest format to  YAML  and paste EXACTLY this,")
    print("       replacing the default content. Then “Next” → “Create”.\n")
    print(_rule())
    print(manifest, end="")
    print(_rule())
    _pause("Press Enter once the app is created")

    print("\n[4/6]  Left sidebar → “Install App” → “Install to Workspace” → “Allow”.")
    print("       Then copy the  Bot User OAuth Token  (starts with  xoxb-).")
    bot_token = _ask("       Paste the bot token (xoxb-…)")

    print("\n[5/6]  Left sidebar → “Basic Information” → “App-Level Tokens”")
    print("       → “Generate Token and Scopes”. Add the scope  connections:write,")
    print("       give it any name, click “Generate”, then copy the token (xapp-…).")
    app_token = _ask("       Paste the app-level token (xapp-…)")

    print("\n[6/6]  That's the manual part done.")
    if not bot_token.startswith("xoxb-"):
        print("       ⚠️  That bot token doesn't start with 'xoxb-' — double-check it.")
    if not app_token.startswith("xapp-"):
        print("       ⚠️  That app token doesn't start with 'xapp-' — double-check it.")
    return bot_token, app_token, app_name


def run(config: str | None = None) -> int:
    """Standalone ``slack-init`` command: guided Slack setup → saved config."""
    import os
    if config:
        os.environ["AGENT2CHAT_CONFIG"] = config

    agent = _choose("AI agent to connect", [(a.name, a.label) for a in adapters.available()],
                    default="claude-code")
    cfg = Config(platform="slack", agent=agent)
    if agent == "generic":
        print("\nGeneric agent: enter the command to run. Use {prompt} where the message goes.")
        cmd = _ask("Command (space-separated)", "my-agent --prompt {prompt}")
        cfg.command = cmd.split()

    cfg.slack_bot_token, cfg.slack_app_token, _ = collect_tokens()

    ids = _ask("\nAllow-listed Slack user id(s), comma-separated (you can add more later)")
    cfg.allowed_user_ids = [i.strip() for i in ids.split(",") if i.strip()]

    try:
        path = save(cfg)
    except Exception as e:
        print(f"\n✗ Could not save config: {e}")
        print("  Fix the tokens and rerun:  python -m agent2chat slack-init")
        return 1

    print(f"\n✓ Saved config to {path}")
    if not cfg.allowed_user_ids:
        print("⚠️  No users allow-listed yet. Start the bridge, DM the bot, use /id to get")
        print("    your Slack user id, then add it to allowed_user_ids.")
    print("\nNext:  python -m agent2chat doctor    # verify the connection")
    print("       python -m agent2chat run       # start the bridge")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(run())

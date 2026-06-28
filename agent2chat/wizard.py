"""Interactive setup wizard: choose a platform + agent, enter secrets, authorize yourself.

Kept deliberately small and linear — it writes a valid config file (0600) and prints the
next step. Everything it asks for can also be edited directly in the JSON afterwards.
"""
from __future__ import annotations

from . import adapters
from .config import Config, config_path, save


def _ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def _choose(label: str, options: list[tuple[str, str]], default: str) -> str:
    print(f"\n{label}:")
    for i, (name, desc) in enumerate(options, 1):
        print(f"  {i}) {name} — {desc}")
    while True:
        raw = _ask("Choose", default)
        if raw in {name for name, _ in options}:
            return raw
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print("  please pick a number or name from the list.")


def run() -> int:
    print("=== Agent2Chat setup ===")
    platform = _choose("Chat platform", [
        ("telegram", "long polling, no public URL needed"),
        ("slack", "Socket Mode, no public URL needed"),
        ("teams", "Bot Framework, needs a reachable HTTPS endpoint"),
    ], default="telegram")

    agent = _choose("AI agent", [(a.name, a.label) for a in adapters.available()],
                    default="claude-code")

    cfg = Config(platform=platform, agent=agent)

    if platform == "telegram":
        cfg.telegram_token = _ask("Telegram bot token (from @BotFather)")
    elif platform == "slack":
        from . import slack_setup
        cfg.slack_bot_token, cfg.slack_app_token, _ = slack_setup.collect_tokens()
    elif platform == "teams":
        cfg.teams_app_id = _ask("Teams app (client) id")
        cfg.teams_app_password = _ask("Teams client secret")
        cfg.teams_tenant_id = _ask("Tenant id (blank = multi-tenant)")
        cfg.webhook_port = int(_ask("Local webhook port", "3978") or "3978")

    if agent == "generic":
        print("\nGeneric agent: enter the command to run. Use {prompt} where the message goes.")
        cmd = _ask("Command (space-separated)", "my-agent --prompt {prompt}")
        cfg.command = cmd.split()

    ids = _ask("\nAllow-listed user id(s), comma-separated (you can add more later)")
    cfg.allowed_user_ids = [i.strip() for i in ids.split(",") if i.strip()]

    path = save(cfg)
    print(f"\n✓ Saved config to {path}")
    if not cfg.allowed_user_ids:
        print("⚠️  No users allow-listed yet. Start the bridge, send it a message, "
              "use /id to get your id, then add it to the config.")
    print("\nNext:  python -m agent2chat doctor      # verify everything")
    print("       python -m agent2chat run         # start the bridge")
    return 0


if __name__ == "__main__":   # pragma: no cover
    raise SystemExit(run())

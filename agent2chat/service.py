"""Generate an OS service unit so the bridge runs in the background and on boot.

The *unit* is printed to **stdout** and the install instructions to **stderr**, so you
can redirect just the unit into a file:

    python -m agent2chat service > ~/.config/systemd/user/agent2chat.service

On Linux this emits a systemd **user** service by default (no root needed; pair it with
``loginctl enable-linger`` to keep running after logout / across reboots). Pass
``--system`` for a system-wide unit (runs via the system manager with ``User=`` set —
robust on headless servers where the per-user bus isn't available). On macOS it emits a
launchd plist.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from .config import CONFIG_ENV, config_path


def _target_user() -> tuple[str, str]:
    """The user the service should run as, and their home. Honours ``$SUDO_USER`` so
    ``sudo python -m agent2chat service --system`` targets the real user, not root."""
    user = os.environ.get("SUDO_USER") or getpass.getuser()
    home = str(Path.home())
    try:
        import pwd
        home = pwd.getpwnam(user).pw_dir
    except (ImportError, KeyError):
        pass
    return user, home


def _python() -> str:
    return sys.executable or "python3"


def _workdir() -> str:
    # Parent of the package dir: lets `-m agent2chat` import cleanly from a source checkout,
    # and is harmless when the package is pip-installed.
    return str(Path(__file__).resolve().parents[1])


def _exec_start() -> str:
    cmd = f"{_python()} -m agent2chat run"
    # If a non-default config is active, bake it in so the service uses the same one.
    import os
    if os.environ.get(CONFIG_ENV):
        cmd += f" --config {config_path()}"
    return cmd


def _systemd_unit() -> str:
    return f"""[Unit]
Description=Agent2Chat bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart={_exec_start()}
WorkingDirectory={_workdir()}
Environment=PYTHONUNBUFFERED=1
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""


def _systemd_system_unit() -> str:
    user, home = _target_user()
    # System units have a minimal PATH, so extend it to where claude/codex commonly land
    # (user-local bin and the npm global prefix), and set HOME so the agent finds its auth.
    path = f"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:{home}/.local/bin:{home}/.npm-global/bin:{home}/.nvm/current/bin"
    return f"""[Unit]
Description=Agent2Chat bridge
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User={user}
WorkingDirectory={_workdir()}
ExecStart={_exec_start()}
Environment=PYTHONUNBUFFERED=1
Environment=HOME={home}
Environment=PATH={path}
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
"""


def _launchd_plist() -> str:
    python, workdir = _python(), _workdir()
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.slonline.agent2chat</string>
  <key>ProgramArguments</key>
  <array>
    <string>{python}</string><string>-m</string><string>agent2chat</string><string>run</string>
  </array>
  <key>WorkingDirectory</key><string>{workdir}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/agent2chat.log</string>
  <key>StandardErrorPath</key><string>/tmp/agent2chat.err</string>
</dict>
</plist>
"""


def print_instructions(system: bool = False) -> int:
    if system and sys.platform != "darwin":
        sys.stdout.write(_systemd_system_unit())
        print(
            "\n# systemd SYSTEM-service setup (Linux, needs root — no user bus required):\n"
            "#   sudo python3 -m agent2chat service --system > /etc/systemd/system/agent2chat.service\n"
            "#   sudo systemctl daemon-reload\n"
            "#   sudo systemctl enable --now agent2chat\n"
            "#   systemctl status agent2chat\n"
            "#   journalctl -u agent2chat -f          # watch logs\n"
            "# Stop:  sudo systemctl disable --now agent2chat\n"
            "# Note: if the agent (claude/codex) isn't found, add its dir to the PATH= line.",
            file=sys.stderr,
        )
        return 0

    if sys.platform == "darwin":
        sys.stdout.write(_launchd_plist())
        print(
            "\n# launchd setup (macOS):\n"
            "#   python -m agent2chat service > ~/Library/LaunchAgents/com.slonline.agent2chat.plist\n"
            "#   launchctl load ~/Library/LaunchAgents/com.slonline.agent2chat.plist\n"
            "#   launchctl list | grep agent2chat        # check it's running\n"
            "#   tail -f /tmp/agent2chat.log             # watch logs\n"
            "# Stop:  launchctl unload ~/Library/LaunchAgents/com.slonline.agent2chat.plist",
            file=sys.stderr,
        )
        return 0

    sys.stdout.write(_systemd_unit())
    print(
        "\n# systemd user-service setup (Linux):\n"
        "#   mkdir -p ~/.config/systemd/user\n"
        "#   python -m agent2chat service > ~/.config/systemd/user/agent2chat.service\n"
        "#   systemctl --user daemon-reload\n"
        "#   systemctl --user enable --now agent2chat\n"
        "#   loginctl enable-linger $USER      # keep running after logout / across reboots\n"
        "#   systemctl --user status agent2chat\n"
        "#   journalctl --user -u agent2chat -f   # watch logs\n"
        "# Stop:  systemctl --user disable --now agent2chat",
        file=sys.stderr,
    )
    return 0

"""Command-line entry point: ``python -m agent2chat <command>``.

Commands:
  setup     interactive wizard (choose platform + agent, enter secrets, authorize yourself)
  run       start the bridge
  doctor    check the current config, agent availability and platform connectivity
  notify    push a message to the first allow-listed user (for cron/background jobs)
  version   print the version
"""
from __future__ import annotations

import argparse
import logging
import os
import sys


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _apply_config_arg(args) -> None:
    if getattr(args, "config", None):
        os.environ["AGENT2CHAT_CONFIG"] = args.config


def _cmd_run(args) -> int:
    from .bridge import Bridge
    from .config import ConfigError, load
    _apply_config_arg(args)
    try:
        cfg = load()
    except ConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    Bridge(cfg).run()
    return 0


def _cmd_doctor(args) -> int:
    from . import adapters, connectors
    from .config import ConfigError, load
    _apply_config_arg(args)
    try:
        cfg = load()
    except ConfigError as e:
        print(f"✗ config: {e}", file=sys.stderr)
        return 2
    print("config:", cfg.redacted())

    agent_cls = adapters.REGISTRY.get(cfg.agent)
    agent_ok = agent_cls.detect() if agent_cls else False
    print(f"agent '{cfg.agent}': {'✓ binary found' if agent_ok else '✗ binary NOT found on PATH'}")

    if not cfg.allowed_user_ids:
        print("⚠️  allowed_user_ids is empty — the bot will refuse everyone.")

    try:
        label = connectors.build(cfg).verify()
        print(f"platform '{cfg.platform}': ✓ {label}")
        platform_ok = True
    except Exception as e:
        print(f"platform '{cfg.platform}': ✗ {e}")
        platform_ok = False

    return 0 if (agent_ok and platform_ok) else 1


def _cmd_notify(args) -> int:
    from . import connectors
    from .config import ConfigError, load
    _apply_config_arg(args)
    try:
        cfg = load()
    except ConfigError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 2
    text = (args.message if args.message is not None else sys.stdin.read()).strip()
    if not text:
        print("✗ nothing to send (pass a message or pipe it on stdin)", file=sys.stderr)
        return 2
    if not cfg.allowed_user_ids:
        print("✗ no owner to notify (allowed_user_ids is empty)", file=sys.stderr)
        return 2
    try:
        connector = connectors.build(cfg)
        connector.verify()
        connector.send_message(cfg.allowed_user_ids[0], text)
    except Exception as e:
        print(f"✗ send failed: {e}", file=sys.stderr)
        return 1
    print("✓ sent")
    return 0


def main(argv: list[str] | None = None) -> int:
    from . import __version__
    parser = argparse.ArgumentParser(
        prog="agent2chat", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    parser.add_argument("-V", "--version", action="version", version=f"agent2chat {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("setup", help="interactive setup wizard")
    run_p = sub.add_parser("run", help="start the bridge")
    run_p.add_argument("--config", help="path to a specific config (run multiple bridges)")
    doc = sub.add_parser("doctor", help="diagnose config, agent and platform connectivity")
    doc.add_argument("--config", help="path to a specific config")
    nt = sub.add_parser("notify", help="push a message to the owner (for cron/background jobs)")
    nt.add_argument("message", nargs="?", help="text to send (omit to read from stdin)")
    nt.add_argument("--config", help="path to a specific config")
    sub.add_parser("version", help="print the version")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    if args.command == "setup":
        from . import wizard
        return wizard.run()
    if args.command == "run":
        return _cmd_run(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "notify":
        return _cmd_notify(args)
    if args.command == "version":
        print(__version__)
        return 0
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)

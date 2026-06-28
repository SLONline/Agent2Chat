"""Adapter for OpenAI's Codex CLI (``codex``).

Uses the non-interactive subcommand: ``codex exec "<prompt>"``. Continuity is handled by
running each conversation in its own working directory; follow-ups pass ``resume --last``
(resume the most recent session). Both commands are overridable in config if your Codex
build uses different flags.

``--skip-git-repo-check`` is required because each conversation runs in its own isolated
working directory, which is not a git repo. Without it Codex refuses with "Not inside a
trusted directory and --skip-git-repo-check was not specified."

Install / auth: https://github.com/openai/codex  (run ``codex`` once to sign in).
"""
from __future__ import annotations

from .base import Adapter


class CodexAdapter(Adapter):
    name = "codex"
    label = "Codex"
    binary = "codex"
    default_command = ["codex", "exec", "--skip-git-repo-check", "{prompt}"]
    # `resume` is a subcommand of `codex exec`; `--last` picks the most recent session.
    continue_command = ["codex", "exec", "resume", "--last", "--skip-git-repo-check", "{prompt}"]

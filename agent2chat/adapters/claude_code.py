"""Adapter for Anthropic's Claude Code CLI (``claude``).

Uses headless ("print") mode: ``claude -p "<prompt>"``. Conversation continuity comes
for free from the per-conversation working directory plus ``--continue`` (which resumes
the most recent conversation in that directory).

Install / auth: https://docs.claude.com/claude-code  (run ``claude`` once to log in).
"""
from __future__ import annotations

from .base import Adapter


class ClaudeCodeAdapter(Adapter):
    name = "claude-code"
    label = "Claude Code"
    binary = "claude"
    default_command = ["claude", "-p", "{prompt}", "--output-format", "text"]
    continue_command = ["claude", "-p", "--continue", "{prompt}", "--output-format", "text"]

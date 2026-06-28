import pytest

from agent2chat import adapters
from agent2chat.adapters import AdapterError
from agent2chat.adapters.claude_code import ClaudeCodeAdapter
from agent2chat.adapters.codex import CodexAdapter


def test_claude_first_turn_argv():
    a = ClaudeCodeAdapter()
    argv = a.build_argv("hello world", is_continuation=False)
    assert argv == ["claude", "-p", "hello world", "--output-format", "text"]


def test_claude_continuation_argv():
    a = ClaudeCodeAdapter()
    argv = a.build_argv("again", is_continuation=True)
    assert "--continue" in argv
    assert "again" in argv


def test_codex_continuation_uses_resume():
    argv = CodexAdapter().build_argv("p", is_continuation=True)
    assert argv == ["codex", "exec", "resume", "--last", "--skip-git-repo-check", "p"]


def test_codex_first_turn_skips_git_check():
    # The isolated per-conversation dir is not a git repo, so this flag is mandatory.
    argv = CodexAdapter().build_argv("p", is_continuation=False)
    assert argv == ["codex", "exec", "--skip-git-repo-check", "p"]


def test_generic_requires_command():
    with pytest.raises(AdapterError):
        adapters.REGISTRY["generic"]()


def test_build_from_config_unknown_agent():
    class Cfg:
        agent = "nope"
        command = None
        continue_command = None
        agent_timeout = 600
    with pytest.raises(AdapterError):
        adapters.build(Cfg())


def test_prompt_substitution_in_token():
    # {prompt} embedded inside a larger token is substituted in place.
    a = ClaudeCodeAdapter(command=["x", "pre-{prompt}-post"])
    assert a.build_argv("Z", is_continuation=False) == ["x", "pre-Z-post"]

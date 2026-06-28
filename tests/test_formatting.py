from agent2chat import formatting


def test_chunk_short_text_unchanged():
    assert formatting.chunk("hello", 100) == ["hello"]
    assert formatting.chunk("", 100) == []


def test_chunk_splits_on_boundaries():
    text = "a" * 60 + "\n\n" + "b" * 60
    parts = formatting.chunk(text, 70)
    assert len(parts) == 2
    assert all(len(p) <= 70 for p in parts)
    assert parts[0].endswith("a")
    assert parts[1].startswith("b")


def test_chunk_hard_split_when_no_boundary():
    parts = formatting.chunk("x" * 250, 100)
    assert all(len(p) <= 100 for p in parts)
    assert "".join(parts) == "x" * 250


def test_telegram_html_bold_and_code():
    out = formatting.markdown_to_telegram_html("**hi** `code` <tag>")
    assert "<b>hi</b>" in out
    assert "<code>code</code>" in out
    assert "&lt;tag&gt;" in out          # raw text is escaped


def test_telegram_html_link():
    out = formatting.markdown_to_telegram_html("[site](https://example.com)")
    assert '<a href="https://example.com">site</a>' in out


def test_slack_mrkdwn_bold_and_link():
    out = formatting.markdown_to_slack_mrkdwn("**bold** and [x](https://y.com)")
    assert "*bold*" in out
    assert "**" not in out
    assert "<https://y.com|x>" in out


def test_slack_mrkdwn_preserves_code():
    out = formatting.markdown_to_slack_mrkdwn("```\n**not bold**\n```")
    assert "**not bold**" in out          # code fences are left untouched


def test_strip_markdown():
    assert formatting.strip_markdown("**a** `b`") == "a b"
